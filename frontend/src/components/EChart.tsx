import type { EChartsOption } from 'echarts'
import { BarChart, LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  VisualMapComponent,
  CanvasRenderer,
])

interface Props {
  option: EChartsOption
  className?: string
  onRangeChange?: (range: [number, number]) => void
}

export function EChart({ option, className = '', onRangeChange }: Props) {
  const element = useRef<HTMLDivElement>(null)
  const chart = useRef<ReturnType<typeof echarts.init> | null>(null)

  useEffect(() => {
    if (!element.current) return
    chart.current = echarts.init(element.current, undefined, { renderer: 'canvas' })
    const observer = new ResizeObserver(() => chart.current?.resize())
    observer.observe(element.current)
    return () => {
      observer.disconnect()
      chart.current?.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true, lazyUpdate: true })
  }, [option])

  useEffect(() => {
    const instance = chart.current
    if (!instance || !onRangeChange) return
    const handler = (event: unknown) => {
      const payload = event as { start?: number; end?: number; batch?: Array<{ start: number; end: number }> }
      const first = payload.batch?.[0]
      onRangeChange([first?.start ?? payload.start ?? 0, first?.end ?? payload.end ?? 100])
    }
    instance.on('datazoom', handler)
    return () => {
      instance.off('datazoom', handler)
    }
  }, [onRangeChange])

  return <div ref={element} className={`chart ${className}`} />
}
