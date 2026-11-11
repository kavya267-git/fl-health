"""The health officer's situation report: per disease and region, this week, the usual level, the status, the
ensemble forecast with its likely range, and how many hospitals reported. Also its CSV and PDF exports.

Every number comes from the surveillance data, the hotspot detector or the stored ensemble run. Nothing is
invented to fill a gap: a missing count, usual level or forecast stays missing and says why.
While the counts are simulated, both exports carry ``data_status.watermark`` on every page and in every row.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.analytics.ensemble_service import EnsembleService
from app.analytics.surveillance_service import SurveillanceService
from app.database import Database
from app.services.audit_service import AuditService
from app.utils.time import utc_now_iso

LIKELY_RANGE_NOTE = "Likely range (based on past errors; often too narrow)"
REPORT_HORIZONS = (2, 3, 4)


class SituationService:
    def __init__(
        self, db: Database, audit: AuditService, surveillance: SurveillanceService, ensemble: EnsembleService, app_version: str
    ):
        self.db = db
        self.audit = audit
        self.surveillance = surveillance
        self.ensemble = ensemble
        self.app_version = app_version

    def _expected_hospitals(self, disease: str) -> Dict[str, int]:
        """How many hospitals have ever reported this disease for each region (the denominator of completeness)."""
        rows = self.db.fetch_all(
            "SELECT region_id, COUNT(DISTINCT hospital_id) AS n FROM surveillance_reports WHERE disease = :d GROUP BY region_id",
            {"d": disease},
        )
        return {r["region_id"]: int(r["n"]) for r in rows}

    def about_forecast(self) -> Dict[str, Any]:
        run = self.ensemble.latest()
        status = self.ensemble.status()
        if run is None:
            return {"available": False, **status}
        return {
            "available": True,
            **status,
            "computed_at": run["computed_at"],
            "data_through": run["data_through"],
            "validation_window": run["validation_window"],
            "members": run["members"],
            "member_labels": run["member_labels"],
            "weights": run["weights"],
            "validation": run["validation"],
            "level": run["level"],
            "rule": (
                "Weights are fitted on the 20 most recent weeks of data (the validation window, ending with the "
                "latest data week) and are non-negative and sum to 1 for each week ahead."
            ),
        }

    def situation(self, jurisdiction: Optional[List[str]] = None, actor: str = "system") -> Dict[str, Any]:
        self.surveillance._require_available()
        run = self.ensemble.latest()
        diseases = []
        for disease in self.surveillance.diseases():
            result = self.surveillance.hotspots(disease["id"], None, actor, jurisdiction)
            expected = self._expected_hospitals(disease["id"])
            week = result["time_period"]
            regions = []
            for region in result["regions"]:
                usual = region["baseline_mean"]
                count = region["case_count"]
                points = (run or {}).get("forecasts", {}).get(f"{disease['id']}:{region['region_id']}")
                excluded = (run or {}).get("excluded", {}).get(f"{disease['id']}:{region['region_id']}")
                regions.append(
                    {
                        "region_id": region["region_id"],
                        "region_name": region["region_name"],
                        "case_count": count,
                        "case_rate": region["case_rate"],
                        "usual_level": usual,
                        "ratio_to_usual": (count / usual) if count is not None and usual else None,
                        "status": region["status"],
                        "status_label": region["status_label"],
                        "reporting_hospitals": region["reporting_hospitals"],
                        "expected_hospitals": expected.get(region["region_id"], 0),
                        "forecast": self._forecast(points, excluded, run),
                    }
                )
            diseases.append({"disease": disease, "week": week, "summary": result["summary"], "regions": regions})
        return {
            "generated_at": utc_now_iso(),
            "jurisdiction": jurisdiction,
            "diseases": diseases,
            "about_forecast": self.about_forecast(),
            "data_status": self.surveillance.data_status(),
            "likely_range_note": LIKELY_RANGE_NOTE,
        }

    @staticmethod
    def _forecast(points: Optional[list], excluded: Optional[str], run: Optional[dict]) -> Dict[str, Any]:
        if run is None:
            return {"available": False, "reason": "The forecast is still being computed."}
        if not points:
            return {"available": False, "reason": f"No forecast: {excluded or 'not enough reported weeks'}."}
        last = date.fromisoformat(run["data_through"])
        weeks = []
        for point in points:
            start = last + timedelta(weeks=point["horizon"])
            weeks.append({**point, "week_start": start.isoformat(), "label": SurveillanceService._period(start.isoformat())["label"]})
        shown = [w for w in weeks if w["horizon"] in REPORT_HORIZONS]
        return {
            "available": True,
            "weeks": weeks,
            "summary": {
                "horizons": list(REPORT_HORIZONS),
                "predicted_low": min(w["predicted"] for w in shown),
                "predicted_high": max(w["predicted"] for w in shown),
                "range_low": min(w["lower"] for w in shown),
                "range_high": max(w["upper"] for w in shown),
            },
        }

    # ------------------------------------------------------------------ exports
    def _rows(self, report: Dict[str, Any]) -> List[Dict[str, Any]]:
        watermark = report["data_status"].get("watermark") or ""
        rows = []
        for block in report["diseases"]:
            for r in block["regions"]:
                f = r["forecast"]
                s = f.get("summary") if f["available"] else None
                rows.append(
                    {
                        "data_flag": watermark,
                        "disease": block["disease"]["label"],
                        "week": block["week"]["label"],
                        "week_start": block["week"]["week_start"],
                        "region_id": r["region_id"],
                        "region": r["region_name"],
                        "cases_this_week": "" if r["case_count"] is None else r["case_count"],
                        "rate_per_100k": "" if r["case_rate"] is None else round(r["case_rate"], 1),
                        "usual_level": "" if r["usual_level"] is None else round(r["usual_level"], 1),
                        "ratio_to_usual": "" if r["ratio_to_usual"] is None else round(r["ratio_to_usual"], 2),
                        "status": r["status_label"],
                        "hospitals_reported": f"{r['reporting_hospitals']} of {r['expected_hospitals']}",
                        "forecast_2_4_weeks": "" if s is None else f"{s['predicted_low']:.0f}-{s['predicted_high']:.0f} per week",
                        "likely_range_2_4_weeks": "" if s is None else f"{s['range_low']:.0f}-{s['range_high']:.0f}",
                        "forecast_note": "" if s else f["reason"],
                    }
                )
        return rows

    def _header_lines(self, report: Dict[str, Any]) -> List[str]:
        status = report["data_status"]
        about = report["about_forecast"]
        lines = []
        if status.get("watermark"):
            lines.append(status["watermark"])
        lines.append(f"MediFed situation report, version {self.app_version}, generated {report['generated_at']}")
        if report["diseases"]:
            lines.append(f"Data through the week starting {report['diseases'][0]['week']['week_start']}")
        if report["jurisdiction"] is not None:
            lines.append(f"Jurisdiction: {', '.join(report['jurisdiction'])}")
        if status.get("population_source"):
            lines.append(f"Rates per 100,000 use the {status['population_source']}")
        lines.append(f"Forecast: {LIKELY_RANGE_NOTE}" if about["available"] else "Forecast: still being computed")
        lines.append("A potential hotspot is a statistical signal for review, not a confirmed rise in illness.")
        return lines

    def export_csv(self, jurisdiction: Optional[List[str]], actor: str) -> str:
        report = self.situation(jurisdiction, actor)
        out = io.StringIO()
        for line in self._header_lines(report):
            out.write(f"# {line}\n")
        rows = self._rows(report)
        writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()) if rows else ["data_flag"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        self._audit_export("csv", report, actor)
        return out.getvalue()

    def export_pdf(self, jurisdiction: Optional[List[str]], actor: str) -> bytes:
        from fpdf import FPDF  # backend/requirements.txt

        report = self.situation(jurisdiction, actor)
        watermark = report["data_status"].get("watermark")
        font_dir = _font_dir()

        class Report(FPDF):
            def header(self):
                if watermark:  # on every page, across the page, behind nothing: it cannot be cropped off
                    self.set_font("DejaVu", "B", 44)
                    self.set_text_color(200, 60, 50)
                    with self.rotation(25, self.w / 2, self.h / 2):
                        self.text(self.w / 2 - self.get_string_width(watermark) / 2, self.h / 2, watermark)
                    self.set_font("DejaVu", "B", 9)
                    self.set_xy(10, 5)
                    self.cell(0, 5, watermark, align="C")
                    self.set_text_color(17, 26, 46)
                self.set_y(12)

            def footer(self):
                self.set_y(-12)
                self.set_font("DejaVu", "", 7)
                self.set_text_color(78, 91, 117)
                self.cell(0, 5, f"{LIKELY_RANGE_NOTE}. Page {self.page_no()}", align="C")

        pdf = Report(orientation="L", unit="mm", format="A4")
        pdf.add_font("DejaVu", "", str(font_dir / "DejaVuSans.ttf"))
        pdf.add_font("DejaVu", "B", str(font_dir / "DejaVuSans-Bold.ttf"))
        pdf.set_auto_page_break(True, margin=15)
        pdf.add_page()
        pdf.set_font("DejaVu", "B", 14)
        pdf.cell(0, 8, "Situation report", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", 8)
        for line in self._header_lines(report)[1:]:
            pdf.cell(0, 4.5, line, new_x="LMARGIN", new_y="NEXT")
        columns = [
            ("Region", 46, "region"),
            ("This week", 20, "cases_this_week"),
            ("Usual", 16, "usual_level"),
            ("Ratio", 14, "ratio_to_usual"),
            ("Status", 32, "status"),
            ("Hospitals", 22, "hospitals_reported"),
            ("Forecast 2-4 wk", 36, "forecast_2_4_weeks"),
            ("Likely range", 26, "likely_range_2_4_weeks"),
            ("Note", 65, "forecast_note"),
        ]
        rows = self._rows(report)
        for block in report["diseases"]:
            pdf.ln(3)
            pdf.set_font("DejaVu", "B", 11)
            pdf.cell(0, 7, f"{block['disease']['label']}, week {block['week']['label']}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("DejaVu", "B", 7.5)
            for title, width, _ in columns:
                pdf.cell(width, 6, title, border="B")
            pdf.ln()
            pdf.set_font("DejaVu", "", 7.5)
            for row in (r for r in rows if r["disease"] == block["disease"]["label"]):
                for _, width, key in columns:
                    pdf.cell(width, 5.5, str(row[key])[: int(width * 0.55)], border="B")
                pdf.ln()
        self._audit_export("pdf", report, actor)
        return bytes(pdf.output())

    def _audit_export(self, kind: str, report: Dict[str, Any], actor: str) -> None:
        self.audit.record(
            "SITUATION_REPORT_EXPORTED",
            actor,
            details={
                "format": kind,
                "jurisdiction": report["jurisdiction"],
                "simulated": bool(report["data_status"].get("simulated")),
            },
        )


def _font_dir() -> Path:
    """DejaVu Sans, bundled (licence in the same folder); it covers the en dash the core PDF fonts lack."""
    return Path(__file__).resolve().parents[1] / "assets" / "fonts"
