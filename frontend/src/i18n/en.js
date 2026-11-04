/**
 * English text for the health officer pages. Keys are shared with other languages (step 4 adds Hindi).
 * {name} marks a value filled in at runtime. Plain words only, and never "outbreak" for an unconfirmed signal.
 */
const en = {
  'situation.title': 'Situation report',
  'situation.description':
    'This week in your area, compared with the usual level for each place, with what is expected over the next few weeks.',
  'situation.jurisdiction': 'Your area: {regions}',
  'situation.week': 'Week {week} ({start} to {end})',
  'situation.exportCsv': 'Download CSV',
  'situation.exportPdf': 'Download PDF',
  'situation.exporting': 'Preparing the file…',
  'situation.exported': 'Downloaded {file}.',
  'situation.populationSource': 'Rates per 100,000 use the {source}.',
  'situation.disclaimer':
    'A potential hotspot is a statistical signal that needs checking. It is not a confirmed rise in illness.',
  'situation.summary':
    '{hotspots} potential hotspot(s), {elevated} elevated, {normal} normal, {insufficient} with insufficient data.',

  'region.cases': '{count} cases this week.',
  'region.casesMissing': 'This week’s total is not available (a hospital’s count was too small to share).',
  'region.casesRate': '{count} cases this week ({rate} per 100,000 people).',
  'region.ratio': 'That is {ratio} times the usual level of about {usual} a week.',
  'region.noUsual': 'There is not yet enough history to say what the usual level is.',
  'region.forecast': 'Expected in 2 to 4 weeks: about {low} to {high} a week (likely range {rangeLow} to {rangeHigh}).',
  'region.noForecast': '{reason}',
  'region.completeness': '{reported} of {expected} hospitals reported this week.',
  'region.completenessNone': 'No hospital has reported for this place yet.',

  'status.NORMAL': 'Normal',
  'status.ELEVATED': 'Elevated',
  'status.CANDIDATE_HOTSPOT': 'Potential hotspot',
  'status.INSUFFICIENT_DATA': 'Insufficient data',

  'about.title': 'About this forecast',
  'about.notReady': 'The forecast is still being computed. It runs in the background and appears here when ready.',
  'about.dataThrough': 'Uses data up to the week starting {date}. Computed {computed}.',
  'about.models': 'It combines {models}. Each week ahead uses its own mix, fitted on the {weeks} most recent weeks ({first} to {last}):',
  'about.weightsRow': '{weeks} week(s) ahead: {weights}',
  'about.likelyRange': 'Likely range (based on past errors; often too narrow).',

  'alerts.title': 'Alerts',
  'alerts.description':
    'An alert opens when a place becomes a potential hotspot. Acknowledge it, look into it, then record what you found.',
  'alerts.empty': 'No alerts for your area.',
  'alerts.filterOpen': 'Open',
  'alerts.filterAcknowledged': 'Acknowledged',
  'alerts.filterClosed': 'Closed',
  'alerts.filterAll': 'All',
  'alerts.raised': '{disease} in {region}, week {week}: {count} cases against a usual {usual}.',
  'alerts.raisedNoCount': '{disease} in {region}, week {week}.',
  'alerts.acknowledge': 'Acknowledge',
  'alerts.acknowledgedBy': 'Acknowledged by {who} on {when}.',
  'alerts.recordOutcome': 'Record outcome',
  'alerts.outcomeLabel': 'What did you find?',
  'alerts.noteLabel': 'Note (how you checked)',
  'alerts.save': 'Save outcome',
  'alerts.closedBy': '{outcome}, recorded by {who} on {when}: {note}',
  'alerts.state.OPEN': 'Open',
  'alerts.state.ACKNOWLEDGED': 'Acknowledged',
  'alerts.state.CLOSED': 'Closed',
  'outcome.CONFIRMED': 'Confirmed',
  'outcome.NOT_CONFIRMED': 'Not confirmed',
  'outcome.REPORTING_ARTEFACT': 'Reporting artefact',

  'common.simulated': 'SIMULATED DATA – NOT REAL CASES',
}

export default en
