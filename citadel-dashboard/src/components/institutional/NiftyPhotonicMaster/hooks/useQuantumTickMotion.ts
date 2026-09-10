'use client'

import { useEffect, useRef, useState } from 'react'

export function useQuantumTickMotion(value: number, threshold = 0) {
  const prevValueRef = useRef(value)
  const [delta, setDelta] = useState(0)
  const [isFlashing, setIsFlashing] = useState(false)
  const [direction, setDirection] = useState<'UP' | 'DOWN' | 'NONE'>('NONE')

  useEffect(() => {
    const prev = prevValueRef.current
    if (value !== prev) {
      const diff = value - prev
      if (Math.abs(diff) >= threshold) {
        setDelta(diff)
        setDirection(diff > 0 ? 'UP' : 'DOWN')
        setIsFlashing(true)
        const timer = setTimeout(() => setIsFlashing(false), 600)
        prevValueRef.current = value
        return () => clearTimeout(timer)
      }
      prevValueRef.current = value
    }
  }, [value, threshold])

  return { delta, isFlashing, direction }
}
