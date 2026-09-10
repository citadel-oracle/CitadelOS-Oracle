'use client'

import { createContext, useContext, type ReactNode } from 'react'

type Theme = 'dark'

const ThemeContext = createContext<{ theme: Theme }>({ theme: 'dark' })

export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <ThemeContext.Provider value={{ theme: 'dark' }}>
      {children}
    </ThemeContext.Provider>
  )
}

export const useTheme = () => useContext(ThemeContext)
