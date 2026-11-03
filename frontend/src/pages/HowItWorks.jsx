import { ShieldCheck } from 'lucide-react'
import { NETWORK_IMAGE } from '../assets/illustrations'
import { Card, CardBody } from '../components/ui/Card'
import { PageHeader } from '../components/ui/Misc'

const STEPS = [
  {
    title: 'Each hospital trains on its own data',
    body: 'A copy of the shared model is trained on the hospital’s own computer, using its own records, ECGs or chest X-rays. That data stays where it is.',
  },
  {
    title: 'Only model updates are sent',
    body: 'When local training finishes, the hospital sends the changed model settings (numbers, not patient records) to the coordinator.',
  },
  {
    title: 'The coordinator averages the updates',
    body: 'The coordinator combines the updates from every hospital in the round into one model. Hospitals that trained on more records count for more.',
  },
  {
    title: 'The improved model goes back',
    body: 'Every hospital receives the new shared model, and the next round starts from it.',
  },
]

const NEVER_LEAVES = [
  'Patient records, names and identifiers',
  'ECG signals and chest X-ray images',
  'Any single patient’s diagnosis or test result',
]

export default function HowItWorks() {
  return (
    <>
      <PageHeader
        title="How it works"
        description="Hospitals build shared models together without sending their patients’ data anywhere. One training round has four steps."
      />

      <Card className="mb-6 overflow-hidden bg-[#f3f8fe]">
        <img
          src={NETWORK_IMAGE.src}
          alt={NETWORK_IMAGE.alt}
          width="1323"
          height="586"
          className="mx-auto block h-auto w-full max-w-3xl bg-[#f3f8fe]"
        />
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <ol aria-label="The four steps of a training round" className="grid gap-4 sm:grid-cols-2">
          {STEPS.map((step, index) => (
            <li key={step.title} className="rounded-lg border border-line bg-surface px-5 py-4 shadow-card">
              <div className="flex items-center gap-3">
                <span
                  aria-hidden="true"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-sm font-semibold text-brand-700"
                >
                  {index + 1}
                </span>
                <h2 className="text-[15px] font-semibold leading-snug text-ink">
                  <span className="sr-only">Step {index + 1}: </span>
                  {step.title}
                </h2>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-muted">{step.body}</p>
            </li>
          ))}
        </ol>

        <Card as="aside" aria-labelledby="never-leaves" className="h-fit border-brand-200 bg-brand-50">
          <CardBody>
            <h2 id="never-leaves" className="flex items-center gap-2 text-[15px] font-semibold text-brand-900">
              <ShieldCheck className="h-4 w-4 shrink-0 text-brand-700" aria-hidden="true" />
              What never leaves a hospital
            </h2>
            <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-ink">
              {NEVER_LEAVES.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <p className="mt-4 text-xs leading-relaxed text-muted">
              What is shared: model updates, how many records each hospital trained on, and weekly case totals per region for disease
              surveillance, with small counts hidden. Model updates can still reveal something about the data they came from, so this
              reduces privacy risk rather than removing it.
            </p>
          </CardBody>
        </Card>
      </div>
    </>
  )
}
