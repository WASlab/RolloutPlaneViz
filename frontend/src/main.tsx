import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@fontsource-variable/manrope'
import '@fontsource/ibm-plex-mono/latin-400.css'
import '@fontsource/ibm-plex-mono/latin-500.css'
import '@fontsource/ibm-plex-mono/latin-600.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1 } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode><QueryClientProvider client={queryClient}><App /></QueryClientProvider></StrictMode>,
)
