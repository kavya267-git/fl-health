/** The "cluster of potential hotspots" layer note and toggle. */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ClusterLayerNote } from '../pages/Surveillance'

const layer = {
  method: { algorithm: 'k-means', label: 'Cluster of potential hotspots' },
  clusters: [{ cluster: 1, label: 'Cluster of potential hotspots 1', region_ids: ['R01', 'R05'], region_names: ['Ashgrove', 'Eastholm'] }],
  features: ['centroid x (km)', 'centroid y (km)', 'case rate per 100,000', 'anomaly score'],
  silhouette: 0.41,
  reason: null,
}

describe('ClusterLayerNote', () => {
  it('lists each cluster, says what a cluster is not, and toggles the layer', async () => {
    const onToggle = vi.fn()
    render(<ClusterLayerNote layer={layer} shown onToggle={onToggle} />)
    expect(screen.getByText('Cluster of potential hotspots 1:')).toBeInTheDocument()
    expect(screen.getByText('Ashgrove, Eastholm')).toBeInTheDocument()
    expect(screen.getByText(/silhouette 0.41/)).toBeInTheDocument()
    expect(screen.getByText(/does not mean a shared cause, and it is not a confirmed event/)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Cluster of potential hotspots'))
    expect(onToggle).toHaveBeenCalledWith(false)
  })

  it('gives the reason when there is nothing to cluster, with the toggle disabled', () => {
    render(<ClusterLayerNote layer={{ ...layer, clusters: [], silhouette: null, reason: '2 potential hotspots this week; at least 3 are needed to look for clusters.' }} shown onToggle={() => {}} />)
    expect(screen.getByText(/at least 3 are needed/)).toBeInTheDocument()
    expect(screen.getByLabelText('Cluster of potential hotspots')).toBeDisabled()
  })

  it('never uses the word outbreak', () => {
    const { container } = render(<ClusterLayerNote layer={layer} shown onToggle={() => {}} />)
    expect(container.textContent.toLowerCase()).not.toContain('outbreak')
  })
})
