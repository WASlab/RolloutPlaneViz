import type { EChartsOption } from 'echarts'
import { useMemo } from 'react'
import type { Breakdown, Series, TaskResult } from '../types'
import { EChart } from './EChart'

const ink = '#171b19'
const muted = '#737b77'
const grid = '#dfe4df'
const cyan = '#00a9a5'
const coral = '#ef765e'
const lime = '#8aa63b'

const base = {
  animationDuration: 420,
  animationEasing: 'cubicOut' as const,
  textStyle: { fontFamily: 'IBM Plex Mono, ui-monospace, monospace', color: ink },
  color: [cyan, coral, lime],
  grid: { left: 52, right: 18, top: 42, bottom: 34 },
  legend: { top: 4, left: 0, itemWidth: 14, itemHeight: 3, textStyle: { color: muted, fontSize: 9 } },
  axisPointer: { link: [{ xAxisIndex: 'all' as const }] },
  tooltip: {
    trigger: 'axis' as const,
    backgroundColor: '#101312',
    borderWidth: 0,
    textStyle: { color: '#f2f0e8', fontSize: 11 },
  },
  aria: { enabled: true },
}

interface TimeChartProps {
  series: Series[]
  range: [number, number]
  onRangeChange: (range: [number, number]) => void
}

export function TimelineChart({ series, range, onRangeChange }: TimeChartProps) {
  const option = useMemo<EChartsOption>(() => ({
    ...base,
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: grid } },
      axisLabel: { color: muted, fontSize: 10, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: grid, type: 'dashed' } },
      axisLabel: { color: muted, fontSize: 10 },
    },
    dataZoom: [{ type: 'inside', start: range[0], end: range[1], filterMode: 'none' }],
    series: series.map((item, index) => ({
      name: item.name,
      type: 'line',
      showSymbol: false,
      sampling: 'lttb',
      smooth: 0.12,
      lineStyle: { width: index === 0 ? 2.5 : 1.6 },
      areaStyle: index === 0 ? { opacity: 0.07 } : undefined,
      data: item.points.map(point => [point.timestamp_ms, point.value]),
    })),
  }), [series, range])
  return <EChart option={option} group="run-time" onRangeChange={onRangeChange} />
}

export function ThroughputChart({ series, range, onRangeChange }: TimeChartProps) {
  const option = useMemo<EChartsOption>(() => ({
    ...base,
    grid: { ...base.grid, left: 58, right: 48 },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: grid } },
      axisLabel: { color: muted, fontSize: 10, hideOverlap: true },
    },
    yAxis: [
      {
        type: 'value',
        scale: true,
        name: 'token/s',
        nameTextStyle: { color: muted },
        splitLine: { lineStyle: { color: grid, type: 'dashed' } },
        axisLabel: { color: muted, fontSize: 10 },
      },
      {
        type: 'value',
        min: 0,
        max: 1,
        name: 'ratio',
        nameTextStyle: { color: muted },
        splitLine: { show: false },
        axisLabel: { color: muted, fontSize: 10, formatter: (value: number) => `${Math.round(value * 100)}%` },
      },
    ],
    dataZoom: [{ type: 'inside', start: range[0], end: range[1], filterMode: 'none' }],
    series: series.map(item => ({
      name: item.name,
      type: 'line',
      yAxisIndex: item.unit === 'ratio' ? 1 : 0,
      showSymbol: false,
      sampling: 'lttb',
      smooth: 0.1,
      lineStyle: { width: 2 },
      areaStyle: item.unit === 'ratio' ? { opacity: 0.08 } : undefined,
      data: item.points.map(point => [point.timestamp_ms, point.value]),
    })),
  }), [series, range])
  return <EChart option={option} group="run-time" onRangeChange={onRangeChange} />
}

export function BreakdownChart({ values }: { values: Breakdown[] }) {
  const option = useMemo<EChartsOption>(() => ({
    ...base,
    legend: { show: false },
    grid: { left: 108, right: 32, top: 8, bottom: 18 },
    xAxis: { type: 'value', max: 100, splitLine: { show: false }, axisLabel: { show: false } },
    yAxis: {
      type: 'category',
      inverse: true,
      data: values.map(value => value.label),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: muted, fontSize: 10 },
    },
    series: [{
      type: 'bar',
      data: values.map((value, index) => ({
        value: value.value,
        itemStyle: { color: index === 0 ? cyan : index === 1 ? coral : '#aeb7b1' },
      })),
      barWidth: 8,
      label: { show: true, position: 'right', formatter: '{c}%', color: ink, fontSize: 10 },
    }],
  }), [values])
  return <EChart option={option} />
}

export function TaskChart({ tasks }: { tasks: TaskResult[] }) {
  const option = useMemo<EChartsOption>(() => ({
    ...base,
    legend: { show: false },
    grid: { left: 152, right: 36, top: 8, bottom: 18 },
    xAxis: {
      type: 'value',
      min: 0,
      max: 1,
      splitLine: { lineStyle: { color: grid, type: 'dashed' } },
      axisLabel: { color: muted, formatter: (value: number) => `${Math.round(value * 100)}%` },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: tasks.map(task => task.task),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: muted, fontSize: 10, width: 140, overflow: 'truncate' },
    },
    visualMap: {
      show: false,
      min: 0.25,
      max: 1,
      dimension: 0,
      inRange: { color: ['#e8a28f', '#e6d985', cyan] },
    },
    series: [{
      type: 'bar',
      data: tasks.map(task => task.success_rate),
      barWidth: 11,
      label: {
        show: true,
        position: 'right',
        formatter: item => `${Math.round(Number(item.value) * 100)}%`,
        color: ink,
        fontSize: 10,
      },
    }],
  }), [tasks])
  return <EChart option={option} />
}
