import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'

interface EChartProps {
  option: echarts.EChartsOption
  height?: number
}

export default function EChart({ option, height = 260 }: EChartProps) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chart.setOption(option)
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
  }, [option])

  return <div ref={ref} style={{ width: '100%', height }} />
}