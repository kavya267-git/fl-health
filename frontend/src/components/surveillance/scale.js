/** Colour scale for the choropleth: light to dark teal over the observed range. */
export const INTENSITY_COLORS = ['#e4f1ee', '#bfe0d9', '#8fc7bc', '#55a597', '#1f7f73', '#0c5049']
export const NO_VALUE_COLOR = '#e3e6e5'

export function buildScale(values) {
  const present = values.filter((v) => v !== null && v !== undefined && !Number.isNaN(v))
  if (present.length === 0) return { min: null, max: null, color: () => NO_VALUE_COLOR, breaks: [] }
  const min = Math.min(...present)
  const max = Math.max(...present)
  const span = max - min || 1
  const steps = INTENSITY_COLORS.length
  const color = (value) => {
    if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE_COLOR
    const index = Math.min(steps - 1, Math.floor(((value - min) / span) * steps))
    return INTENSITY_COLORS[index]
  }
  const breaks = INTENSITY_COLORS.map((fill, index) => ({
    fill,
    from: min + (span * index) / steps,
    to: min + (span * (index + 1)) / steps,
  }))
  return { min, max, color, breaks }
}

/** [[south, west], [north, east]] for a GeoJSON FeatureCollection of polygons. */
export function geojsonBounds(collection) {
  let south = Infinity
  let west = Infinity
  let north = -Infinity
  let east = -Infinity
  const visit = (coordinates) => {
    if (typeof coordinates[0] === 'number') {
      const [lon, lat] = coordinates
      south = Math.min(south, lat)
      north = Math.max(north, lat)
      west = Math.min(west, lon)
      east = Math.max(east, lon)
    } else {
      coordinates.forEach(visit)
    }
  }
  collection.features.forEach((feature) => visit(feature.geometry.coordinates))
  if (!Number.isFinite(south))
    return [
      [-1, -1],
      [1, 1],
    ]
  return [
    [south, west],
    [north, east],
  ]
}
