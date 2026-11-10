import { Download, Info } from 'lucide-react'
import { useState } from 'react'
import { HotspotStatusBadge, SimulatedTag } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Note, PageHeader } from '../components/ui/Misc'
import { AsyncView } from '../components/ui/StateViews'
import { useApi } from '../hooks/useApi'
import { usePolling } from '../hooks/usePolling'
import { currentLanguage, translate } from '../i18n'
import { toApiError } from '../services/api'
import { api } from '../services/endpoints'
import { HOTSPOT_ORDER } from '../utils/constants'
import { formatDate, formatDateTime, formatNumber } from '../utils/format'

const whole = (value) => formatNumber(Math.round(value))

/** One region in plain sentences, built only from the numbers the server sent. */
export function regionSentences(region, t) {
  const lines = []
  if (region.case_count === null || region.case_count === undefined) lines.push(t('region.casesMissing'))
  else if (region.case_rate !== null && region.case_rate !== undefined)
    lines.push(t('region.casesRate', { count: formatNumber(region.case_count), rate: formatNumber(region.case_rate, 1) }))
  else lines.push(t('region.cases', { count: formatNumber(region.case_count) }))

  if (region.ratio_to_usual !== null && region.ratio_to_usual !== undefined)
    lines.push(t('region.ratio', { ratio: formatNumber(region.ratio_to_usual, 1), usual: whole(region.usual_level) }))
  else if (region.case_count !== null) lines.push(t('region.noUsual'))

  const forecast = region.forecast
  if (forecast.available) {
    const s = forecast.summary
    lines.push(
      t('region.forecast', { low: whole(s.predicted_low), high: whole(s.predicted_high), rangeLow: whole(s.range_low), rangeHigh: whole(s.range_high) }),
    )
  } else lines.push(t('region.noForecast', { reason: forecast.reason }))

  lines.push(
    region.expected_hospitals
      ? t('region.completeness', { reported: region.reporting_hospitals, expected: region.expected_hospitals })
      : t('region.completenessNone'),
  )
  return lines
}

function AboutForecast({ about, t }) {
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Info className="h-4 w-4 text-brand-700" aria-hidden="true" />{t('about.title')}</span>} />
      <CardBody className="space-y-2 text-sm leading-relaxed text-ink">
        {about.available ? (
          <>
            <p>{t('about.dataThrough', { date: formatDate(about.data_through), computed: formatDateTime(about.computed_at) })}</p>
            <p>
              {t('about.models', {
                models: about.members.map((m) => about.member_labels[m]).join(', '),
                weeks: about.validation_window.weeks,
                first: formatDate(about.validation_window.first_week),
                last: formatDate(about.validation_window.last_week),
              })}
            </p>
            <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-muted">
              {Object.entries(about.weights).map(([horizon, weights]) => (
                <li key={horizon}>
                  {t('about.weightsRow', {
                    weeks: horizon,
                    weights: about.members.map((m) => `${about.member_labels[m]} ${formatNumber(weights[m] * 100)}%`).join(', '),
                  })}
                </li>
              ))}
            </ul>
            <p className="text-[13px] text-muted">{t('about.likelyRange')}</p>
          </>
        ) : (
          <p className="text-muted">{t('about.notReady')}</p>
        )}
      </CardBody>
    </Card>
  )
}

function DiseaseBlock({ block, t }) {
  const regions = [...block.regions].sort(
    (a, b) => HOTSPOT_ORDER.indexOf(a.status) - HOTSPOT_ORDER.indexOf(b.status) || a.region_name.localeCompare(b.region_name),
  )
  const s = block.summary
  return (
    <Card>
      <CardHeader
        title={`${block.disease.label}`}
        description={`${t('situation.week', { week: block.week.label, start: formatDate(block.week.week_start), end: formatDate(block.week.week_end) })} · ${t('situation.summary', {
          hotspots: s.CANDIDATE_HOTSPOT,
          elevated: s.ELEVATED,
          normal: s.NORMAL,
          insufficient: s.INSUFFICIENT_DATA,
        })}`}
      />
      <ul className="divide-y divide-line">
        {regions.map((region) => (
          <li key={region.region_id} className="grid gap-2 px-5 py-3.5 sm:grid-cols-[14rem_1fr]">
            <div className="flex items-start justify-between gap-2 sm:block">
              <p className="font-semibold text-ink">{region.region_name}</p>
              <div className="sm:mt-1">
                <HotspotStatusBadge status={region.status} />
              </div>
            </div>
            <div className="space-y-0.5 text-sm leading-relaxed text-ink">
              {regionSentences(region, t).map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export default function SituationReport() {
  const language = currentLanguage()
  const t = (key, values) => translate(language, key, values)
  const state = useApi(() => api.situation(), [])
  const notReady = state.status === 'success' && !state.data.about_forecast.available
  // While the forecast is being computed in the background, look again every 20 seconds.
  usePolling(() => state.reload({ silent: true }), 20000, notReady)
  const [busy, setBusy] = useState(null)
  const [message, setMessage] = useState(null)

  async function exportAs(format) {
    setBusy(format)
    setMessage(null)
    try {
      const file = await api.downloadSituation(format)
      setMessage({ tone: 'ok', text: t('situation.exported', { file }) })
    } catch (failure) {
      setMessage({ tone: 'alert', text: toApiError(failure).message })
    } finally {
      setBusy(null)
    }
  }

  return (
    <AsyncView state={state} what="the situation report">
      {(report) => (
        <>
          <PageHeader
            title={t('situation.title')}
            description={t('situation.description')}
            actions={
              <>
                {report.data_status.simulated ? <SimulatedTag compact /> : null}
                <Button icon={Download} loading={busy === 'csv'} disabled={busy !== null} onClick={() => exportAs('csv')}>
                  {t('situation.exportCsv')}
                </Button>
                <Button icon={Download} loading={busy === 'pdf'} disabled={busy !== null} onClick={() => exportAs('pdf')}>
                  {t('situation.exportPdf')}
                </Button>
              </>
            }
          />
          <div className="space-y-6">
            {report.data_status.watermark ? (
              <p
                data-testid="situation-watermark"
                className="rounded-md border-2 border-alert/50 bg-alert-soft px-4 py-2 text-center text-sm font-bold uppercase tracking-wider text-alert"
              >
                {report.data_status.watermark}
              </p>
            ) : null}
            {message ? <Note tone={message.tone}>{message.text}</Note> : null}
            {report.jurisdiction ? (
              <p className="text-sm text-muted">
                {t('situation.jurisdiction', {
                  regions: report.diseases[0]?.regions.map((r) => r.region_name).sort().join(', ') || report.jurisdiction.join(', '),
                })}
              </p>
            ) : null}
            <Note>{t('situation.disclaimer')}</Note>
            <div className="grid gap-6 xl:grid-cols-[1fr_22rem]">
              <div className="space-y-6">
                {report.diseases.map((block) => (
                  <DiseaseBlock key={block.disease.id} block={block} t={t} />
                ))}
              </div>
              <div className="space-y-6">
                <AboutForecast about={report.about_forecast} t={t} />
                {report.data_status.population_source ? (
                  <p className="text-xs text-muted">{t('situation.populationSource', { source: report.data_status.population_source })}</p>
                ) : null}
              </div>
            </div>
          </div>
        </>
      )}
    </AsyncView>
  )
}
