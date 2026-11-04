import { useEffect, useMemo, useRef } from 'react'
import { GeoJSON, MapContainer, TileLayer } from 'react-leaflet'
import { HOTSPOT_STATUS } from '../../utils/constants'
import { geojsonBounds } from './scale'

/** Base-map tiles are opt-in: without VITE_MAP_TILE_URL the regions are drawn on a plain ground. */
const TILE_URL = import.meta.env.VITE_MAP_TILE_URL || ''
const TILE_ATTRIBUTION = import.meta.env.VITE_MAP_TILE_ATTRIBUTION || ''

/**
 * Choropleth of regions. Fill shows disease intensity; the outline shows the hotspot status.
 *
 * The view is locked to the loaded regions: it cannot be panned away or zoomed out past them, so a state's
 * districts are shown as that state alone, never as part of a wider (e.g. national) map. Base-map tiles are
 * drawn only for real boundaries and only when VITE_MAP_TILE_URL is set; simulated regions are not a real
 * place, so they always sit on a plain ground.
 */
export function RegionMap({ geojson, dataKey, scale, valueKey, selectedId, onSelect, showTiles, watermark }) {
  const bounds = useMemo(() => geojsonBounds(geojson), [geojson])
  const tiles = Boolean(showTiles && TILE_URL)
  const selectRef = useRef(onSelect)
  useEffect(() => {
    selectRef.current = onSelect
  }, [onSelect])

  const style = useMemo(
    () => (feature) => {
      const { status, region_id: regionId } = feature.properties
      const selected = regionId === selectedId
      const flagged = status === 'CANDIDATE_HOTSPOT' || status === 'ELEVATED'
      return {
        fillColor: scale.color(feature.properties[valueKey]),
        fillOpacity: tiles ? 0.72 : 1,
        color: selected ? '#111a2e' : flagged ? HOTSPOT_STATUS[status].color : '#ffffff',
        weight: selected ? 3.5 : status === 'CANDIDATE_HOTSPOT' ? 3 : status === 'ELEVATED' ? 2.5 : 1,
        dashArray: status === 'ELEVATED' && !selected ? '6 4' : undefined,
      }
    },
    [scale, valueKey, selectedId, tiles],
  )

  const onEachFeature = (feature, layer) => {
    const { region_name: name, status_label: label } = feature.properties
    layer.bindTooltip(`${name}: ${label}`, { sticky: true })
    layer.on({ click: () => selectRef.current(feature.properties.region_id) })
  }

  return (
    <div
      role="group"
      aria-label="Map of regions coloured by disease intensity. The table below lists the same regions."
      className="relative isolate"
    >
      <MapContainer
        key={`${tiles ? 'tiles' : 'plain'}:${bounds.flat().join(',')}`}
        bounds={bounds}
        boundsOptions={{ padding: [12, 12] }}
        maxBounds={padBounds(bounds, 0.15)}
        maxBoundsViscosity={1}
        scrollWheelZoom={false}
        zoomSnap={0.25}
        attributionControl={tiles}
        whenReady={(event) => event.target.setMinZoom(event.target.getZoom())}
        className="h-[26rem] w-full"
      >
        {tiles ? <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} /> : null}
        {/* Flagged regions are drawn last so their outlines sit on top of their neighbours'. */}
        <GeoJSON key={dataKey} data={orderForDrawing(geojson)} style={style} onEachFeature={onEachFeature} />
      </MapContainer>
      {watermark ? (
        // Part of the map itself, above the regions and not dismissable; clicks pass through to the map.
        <div className="pointer-events-none absolute inset-0 z-[500] flex items-center justify-center overflow-hidden rounded-lg">
          <p
            data-testid="map-watermark"
            className="-rotate-12 select-none whitespace-nowrap rounded border-2 border-alert/60 bg-surface/70 px-4 py-2 text-lg font-bold uppercase tracking-wider text-alert sm:text-2xl"
          >
            {watermark}
          </p>
        </div>
      ) : null}
    </div>
  )
}

/** [[south, west], [north, east]] grown by ``share`` of its size on every side. */
export function padBounds([[south, west], [north, east]], share) {
  const dLat = (north - south) * share
  const dLon = (east - west) * share
  return [
    [south - dLat, west - dLon],
    [north + dLat, east + dLon],
  ]
}

const DRAW_ORDER = { INSUFFICIENT_DATA: 0, NORMAL: 0, ELEVATED: 1, CANDIDATE_HOTSPOT: 2 }

function orderForDrawing(geojson) {
  const features = [...geojson.features].sort((a, b) => (DRAW_ORDER[a.properties.status] ?? 0) - (DRAW_ORDER[b.properties.status] ?? 0))
  return { ...geojson, features }
}
