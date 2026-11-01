import { useEffect, useRef } from 'react'

const SCALE = 5 // each source pixel is drawn as a 5x5 block, so nothing is smoothed or invented

/**
 * Draws the image and, on top of it, the importance heat map.
 * Warmer and more opaque means the area mattered more to the prediction.
 */
export function HeatmapCanvas({ imageBase64, heatmap, showOverlay }) {
  const canvasRef = useRef(null)
  const size = heatmap.length

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return undefined
    const context = canvas.getContext('2d')
    const image = new Image()
    let cancelled = false
    image.onload = () => {
      if (cancelled) return
      context.imageSmoothingEnabled = false
      context.clearRect(0, 0, canvas.width, canvas.height)
      context.drawImage(image, 0, 0, canvas.width, canvas.height)
      if (!showOverlay) return
      for (let row = 0; row < size; row += 1) {
        for (let col = 0; col < heatmap[row].length; col += 1) {
          const heat = heatmap[row][col]
          if (heat <= 0.05) continue
          // Yellow (low) to red (high).
          context.fillStyle = `rgba(${220 + Math.round(35 * heat)}, ${Math.round(190 * (1 - heat))}, 30, ${0.12 + 0.5 * heat})`
          context.fillRect(col * SCALE, row * SCALE, SCALE, SCALE)
        }
      }
    }
    image.src = `data:image/png;base64,${imageBase64}`
    return () => {
      cancelled = true
    }
  }, [imageBase64, heatmap, showOverlay, size])

  return (
    <canvas
      ref={canvasRef}
      width={size * SCALE}
      height={size * SCALE}
      className="w-full max-w-xs rounded-md border border-line"
      style={{ imageRendering: 'pixelated' }}
      role="img"
      aria-label={showOverlay ? 'Input image with the importance heat map drawn over it' : 'Input image'}
    />
  )
}
