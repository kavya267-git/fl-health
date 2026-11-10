import { useState } from 'react'
import { toApiError } from '../../services/api'
import { api } from '../../services/endpoints'
import { MODALITIES, MODALITY_ORDER, availabilityLabel } from '../../utils/constants'
import { Button } from '../ui/Button'
import { Field, Modal, Note, Select, inputClass } from '../ui/Misc'

/**
 * Collects the round settings and asks the server to create the round.
 * The dialog closes only after the server has confirmed the round exists.
 */
export function StartRoundDialog({ modality: initialModality, hospitals, onClose, onStarted }) {
  const [modality, setModality] = useState(initialModality)
  const [selected, setSelected] = useState(() => hospitals.filter((h) => h.online).map((h) => h.id))
  const [localEpochs, setLocalEpochs] = useState(2)
  const [learningRate, setLearningRate] = useState(0.003)
  const [batchSize, setBatchSize] = useState(32)
  const [minParticipants, setMinParticipants] = useState(2)
  const [deadlineSeconds, setDeadlineSeconds] = useState(600)
  const [dpEnabled, setDpEnabled] = useState(false)
  const [clipNorm, setClipNorm] = useState(1.0)
  const [noiseMultiplier, setNoiseMultiplier] = useState(0.1)
  const [missingPercent, setMissingPercent] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const eligible = hospitals.filter((h) => h.online && h.modalities.includes(modality))
  const chosen = eligible.filter((h) => selected.includes(h.id))
  const canStart = chosen.length >= minParticipants && !busy

  const toggle = (id) => setSelected((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]))

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const round = await api.startRound({
        modality,
        hospital_ids: chosen.map((h) => h.id),
        local_epochs: Number(localEpochs),
        batch_size: Number(batchSize),
        learning_rate: Number(learningRate),
        min_participants: Number(minParticipants),
        auto_aggregate: true,
        deadline_seconds: Number(deadlineSeconds),
        simulated_missing_rate: modality === 'ehr' ? Number(missingPercent) / 100 : 0,
        differential_privacy: {
          enabled: dpEnabled,
          clip_norm: Number(clipNorm),
          noise_multiplier: dpEnabled ? Number(noiseMultiplier) : 0,
        },
      })
      onStarted(round)
    } catch (failure) {
      setError(toApiError(failure).message)
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Start a new round"
      onClose={busy ? () => {} : onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="start-round-form" loading={busy} disabled={!canStart}>
            Start round
          </Button>
        </>
      }
    >
      <form id="start-round-form" onSubmit={submit} className="space-y-5">
        {error ? (
          <Note tone="alert" title="The round was not started">
            {error}
          </Note>
        ) : null}

        <Field
          label="Model to train"
          htmlFor="round-modality"
          hint="Each modality has its own model and its own aggregation. They are never averaged together."
        >
          <Select
            id="round-modality"
            value={modality}
            onChange={setModality}
            options={MODALITY_ORDER.map((m) => ({ value: m, label: `${MODALITIES[m].label} (${MODALITIES[m].name})` }))}
          />
        </Field>

        <fieldset>
          <legend className="text-sm font-medium text-ink">Participating hospitals</legend>
          <div className="mt-2 space-y-1.5">
            {hospitals.map((hospital) => {
              const available = hospital.online && hospital.modalities.includes(modality)
              return (
                <label key={hospital.id} className={`flex items-center gap-2.5 text-sm ${available ? 'text-ink' : 'text-faint'}`}>
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-[#24489a]"
                    disabled={!available}
                    checked={available && selected.includes(hospital.id)}
                    onChange={() => toggle(hospital.id)}
                  />
                  {hospital.name}
                  {!hospital.online ? <span className="text-xs">({availabilityLabel(hospital).toLowerCase()})</span> : null}
                  {hospital.online && !available ? <span className="text-xs">(no {MODALITIES[modality].label} data)</span> : null}
                </label>
              )
            })}
          </div>
          {chosen.length < minParticipants ? (
            <p className="mt-2 text-xs text-alert">
              Select at least {minParticipants} hospital{minParticipants === 1 ? '' : 's'}.
            </p>
          ) : null}
        </fieldset>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Local epochs" htmlFor="round-epochs" hint="Passes over each hospital's data per round.">
            <input
              id="round-epochs"
              type="number"
              min={1}
              max={20}
              value={localEpochs}
              onChange={(e) => setLocalEpochs(e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Learning rate" htmlFor="round-lr">
            <input
              id="round-lr"
              type="number"
              min={0.0001}
              max={1}
              step="any"
              value={learningRate}
              onChange={(e) => setLearningRate(e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Batch size" htmlFor="round-batch">
            <input
              id="round-batch"
              type="number"
              min={2}
              max={512}
              value={batchSize}
              onChange={(e) => setBatchSize(e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Minimum hospitals" htmlFor="round-min" hint="The round fails if fewer deliver a valid update.">
            <input
              id="round-min"
              type="number"
              min={1}
              max={hospitals.length}
              value={minParticipants}
              onChange={(e) => setMinParticipants(Number(e.target.value))}
              className={inputClass}
            />
          </Field>
          <Field
            label="Deadline (seconds)"
            htmlFor="round-deadline"
            hint="Hospitals that have not sent an update by then are dropped; the round continues if enough remain."
          >
            <input
              id="round-deadline"
              type="number"
              min={10}
              max={86400}
              value={deadlineSeconds}
              onChange={(e) => setDeadlineSeconds(e.target.value)}
              className={inputClass}
            />
          </Field>
        </div>

        {modality === 'ehr' ? (
          <Field
            label="Simulated missing values (%)"
            htmlFor="round-missing"
            hint="Test setting. Each hospital blanks this share of its EHR values at random and fills them in by nearest-neighbour imputation, fitted on its own training records only. 0 = off."
          >
            <input
              id="round-missing"
              type="number"
              min={0}
              max={50}
              step="any"
              value={missingPercent}
              onChange={(e) => setMissingPercent(e.target.value)}
              className={inputClass}
            />
          </Field>
        ) : null}

        <fieldset className="rounded-md border border-line p-4">
          <legend className="px-1 text-sm font-medium text-ink">Differential privacy (prototype)</legend>
          <label className="flex items-start gap-2.5 text-sm text-ink">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-[#24489a]"
              checked={dpEnabled}
              onChange={(e) => setDpEnabled(e.target.checked)}
            />
            <span>
              Clip each update and add Gaussian noise before it leaves the hospital
              <span className="mt-0.5 block text-xs leading-snug text-muted">
                Noise lowers model quality. With only four hospitals, even small noise is noticeable.
              </span>
            </span>
          </label>
          {dpEnabled ? (
            <div className="mt-4 grid grid-cols-2 gap-4">
              <Field label="Clip norm" htmlFor="round-clip" hint="Maximum L2 size of an update.">
                <input
                  id="round-clip"
                  type="number"
                  min={0.01}
                  step="any"
                  value={clipNorm}
                  onChange={(e) => setClipNorm(e.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="Noise multiplier" htmlFor="round-noise" hint="Noise standard deviation as a multiple of the clip norm.">
                <input
                  id="round-noise"
                  type="number"
                  min={0.001}
                  step="any"
                  value={noiseMultiplier}
                  onChange={(e) => setNoiseMultiplier(e.target.value)}
                  className={inputClass}
                />
              </Field>
            </div>
          ) : null}
        </fieldset>
      </form>
    </Modal>
  )
}
