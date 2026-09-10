export const formatCurrency = (value: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value)
export const formatPercentage = (value: number) => `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value)}%`
export const formatTimestamp = (value: string | Date) => new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'medium', timeZone: 'Asia/Kolkata' }).format(new Date(value))
export const formatDuration = (seconds: number) => `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`
