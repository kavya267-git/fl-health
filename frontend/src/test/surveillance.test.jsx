/** Surveillance page: map rendering, region selection, wording and error handling. */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { geojsonBounds, buildScale } from '../components/surveillance/scale'
import Surveillance from '../pages/Surveillance'
import { ApiError } from '../services/api'
import { api } from '../services/endpoints'
import { analyticsOptions, hotspots } from './fixtures'

vi.mock('../services/endpoints', () => ({ api: { analyticsOptions: vi.fn(), hotspots: vi.fn() } }))

// Leaflet needs a real layout engine, so the map is replaced by a stand-in
// that exposes what the page passes to it.
vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }) => <div data-testid="map">{children}</div>,
  TileLayer: () => <div data-testid="tiles" />,
  GeoJSON: ({ data, style, onEachFeature }) => (
    <div>
      {data.features.map((feature) => {
        const handlers = {}
        onEachFeature(feature, { bindTooltip: () => {}, on: (h) => Object.assign(handlers, h) })
        const { color, fillColor } = style(feature)
        return (
          <button
            key={feature.properties.region_id}
            data-testid={`region-${feature.properties.region_id}`}
            data-outline={color}
            data-fill={fillColor}
            onClick={() => handlers.click()}
          >
            {feature.properties.region_name}
          </button>
        )
      })}
    </div>
  ),
}))

beforeEach(() => {
  vi.resetAllMocks()
  api.analyticsOptions.mockResolvedValue(analyticsOptions)
  api.hotspots.mockResolvedValue(hotspots)
})

describe('Surveillance page', () => {
  it('draws one map region per region and outlines the potential hotspot', async () => {
    render(<Surveillance />)
    expect(await screen.findByTestId('map')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^region-/)).toHaveLength(3)
    expect(screen.getByTestId('region-R01')).toHaveAttribute('data-outline', '#b3261e')
    expect(screen.getByTestId('region-R02')).toHaveAttribute('data-outline', '#ffffff')
    // A region without a complete count gets the neutral "no value" fill, not a low-intensity colour.
    expect(screen.getByTestId('region-R03')).toHaveAttribute('data-fill', '#e3e6e5')
  })

  it('stamps a permanent watermark on the map when real boundaries carry simulated counts', async () => {
    const realBoundaries = {
      ...hotspots,
      data_status: {
        ...hotspots.data_status,
        simulated: true,
        geometry_simulated: false,
        watermark: 'SIMULATED DATA – NOT REAL CASES',
        geometry_notes: 'Vijayanagara is not separate in this source.',
        geometry_attribution: 'District boundaries: geoBoundaries, ODbL 1.0.',
      },
    }
    api.hotspots.mockResolvedValue(realBoundaries)
    render(<Surveillance />)
    expect(await screen.findByTestId('map-watermark')).toHaveTextContent('SIMULATED DATA – NOT REAL CASES')
    expect(screen.getByText('Vijayanagara is not separate in this source.')).toBeInTheDocument()
    expect(screen.getByText('District boundaries: geoBoundaries, ODbL 1.0.')).toBeInTheDocument()
  })

  it('needs no watermark on the fictional regions, which already say they are not a real place', async () => {
    render(<Surveillance />)
    await screen.findByTestId('map')
    expect(screen.queryByTestId('map-watermark')).not.toBeInTheDocument()
  })

  it('draws no base map under simulated regions', async () => {
    render(<Surveillance />)
    await screen.findByTestId('map')
    expect(screen.queryByTestId('tiles')).not.toBeInTheDocument()
    expect(screen.getByText(/regions are fictional/)).toBeInTheDocument()
  })

  it('shows the selected region’s figures when a region is clicked on the map', async () => {
    render(<Surveillance />)
    expect(await screen.findByText(/Select a region on the map/)).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('region-R01'))
    const panel = screen.getByRole('heading', { name: 'Ashgrove' }).closest('div').parentElement
    for (const term of ['Region', 'Disease', 'Cases', 'Case rate', 'Anomaly score', 'Status', 'Time period', 'Data status']) {
      expect(within(panel).getByText(term)).toBeInTheDocument()
    }
    expect(within(panel).getByText('120')).toBeInTheDocument()
    expect(within(panel).getByText('60.0 per 100,000')).toBeInTheDocument()
    expect(within(panel).getByText('4.20 (z-score)')).toBeInTheDocument()
  })

  it('shows "Not available" rather than zero for a region without a complete count', async () => {
    render(<Surveillance />)
    await userEvent.click(await screen.findByRole('button', { name: 'Calderwick', pressed: false }))
    const panel = screen.getByRole('heading', { name: 'Calderwick' }).closest('div').parentElement
    expect(within(panel).getAllByText('Not available')).toHaveLength(3)
  })

  it('uses "Potential hotspot" and never calls a flag an outbreak', async () => {
    render(<Surveillance />)
    await screen.findByTestId('map')
    expect(screen.getAllByText('Potential hotspot').length).toBeGreaterThan(0)
    expect(screen.getByText(/not a confirmed outbreak/)).toBeInTheDocument()
    const mentions = screen.getAllByText(/outbreak/i)
    expect(mentions).toHaveLength(1) // only the disclaimer
  })

  it('requests data for the chosen disease', async () => {
    render(<Surveillance />)
    await screen.findByTestId('map')
    expect(api.hotspots).toHaveBeenLastCalledWith('dengue', '2026-09-21')
    await userEvent.selectOptions(screen.getByLabelText('Disease'), 'influenza_like_illness')
    expect(api.hotspots).toHaveBeenLastCalledWith('influenza_like_illness', '2026-09-21')
  })

  it('shows an error with Retry and recovers', async () => {
    api.hotspots.mockRejectedValueOnce(new ApiError('server', 'The server hit an unexpected error.', 500))
    render(<Surveillance />)
    expect(await screen.findByText('Unable to retrieve surveillance data.')).toBeInTheDocument()
    expect(screen.queryByTestId('map')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByTestId('map')).toBeInTheDocument()
  })

  it('explains when surveillance data is not configured', async () => {
    api.analyticsOptions.mockRejectedValue(new ApiError('unavailable', 'No region boundaries are configured.', 503))
    render(<Surveillance />)
    expect(await screen.findByText('Server unavailable')).toBeInTheDocument()
    expect(screen.getByText(/No region boundaries are configured/)).toBeInTheDocument()
  })
})

describe('map helpers', () => {
  it('computes bounds as [[south, west], [north, east]]', () => {
    expect(geojsonBounds(hotspots.geojson)).toEqual([
      [0, 0],
      [1, 3],
    ])
  })

  it('maps values onto the colour ramp and leaves missing values neutral', () => {
    const scale = buildScale([10, 20, 30, null])
    expect(scale.min).toBe(10)
    expect(scale.max).toBe(30)
    expect(scale.color(10)).toBe('#e6eefa')
    expect(scale.color(30)).toBe('#173a7e')
    expect(scale.color(null)).toBe('#e3e6e5')
    expect(buildScale([null]).min).toBeNull()
  })
})
