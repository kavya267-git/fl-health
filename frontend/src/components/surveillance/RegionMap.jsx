import { useEffect, useMemo, useRef } from 'react'
import { GeoJSON, MapContainer, TileLayer } from 'react-leaflet'
import { HOTSPOT_STATUS } from '../../utils/constants'
import { geojsonBounds } from './scale'

const TILE_URL = import.meta.env.VITE_MAP_TILE_URL || 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

/**
 * Choropleth of regions. Fill shows disease intensity; the outline shows the
 * hotspot status. Background map tiles are drawn only for real boundaries -
 * simulated regions are not a real place, so they are shown on a plain ground.
 */
export function RegionMap({ geojson, dataKey, scale, valueKey, selectedId, onSelect, showTiles }) {
  const bounds = useMemo(() => geojsonBounds(geojson), [geojson])
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
        fillOpacity: showTiles ? 0.72 : 1,
        color: selected ? '#13211e' : flagged ? HOTSPOT_STATUS[status].color : '#ffffff',
        weight: selected ? 3.5 : status === 'CANDIDATE_HOTSPOT' ? 3 : status === 'ELEVATED' ? 2.5 : 1,
        dashArray: status === 'ELEVATED' && !selected ? '6 4' : undefined,
      }
    },
    [scale, valueKey, selectedId, showTiles],
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
      className="isolate"
    >
      <MapContainer
        key={showTiles ? 'tiles' : 'plain'}
        bounds={bounds}
        boundsOptions={{ padding: [12, 12] }}
        scrollWheelZoom={false}
        zoomSnap={0.25}
        attributionControl={showTiles}
        className="h-[26rem] w-full"
      >
        {showTiles ? <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} /> : null}
        {/* Flagged regions are drawn last so their outlines sit on top of their neighbours'. */}
        <GeoJSON key={dataKey} data={orderForDrawing(geojson)} style={style} onEachFeature={onEachFeature} />
      </MapContainer>
    </div>
  )
}

const DRAW_ORDER = { INSUFFICIENT_DATA: 0, NORMAL: 0, ELEVATED: 1, CANDIDATE_HOTSPOT: 2 }

function orderForDrawing(geojson) {
  const features = [...geojson.features].sort((a, b) => (DRAW_ORDER[a.properties.status] ?? 0) - (DRAW_ORDER[b.properties.status] ?? 0))
  return { ...geojson, features }
}
