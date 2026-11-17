import { AlertTriangle, RotateCcw } from 'lucide-react'
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'

type Props = { children: ReactNode }
type State = { error: Error | null }

/**
 * Catches render errors in one page so a bug shows a message instead of unmounting the whole app
 * (a blank white screen). The layout keys this boundary by route, so navigating away resets it.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page crashed:', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="mx-auto mt-10 max-w-lg rounded-xl border border-destructive/40 bg-destructive/5 p-6 text-center">
        <AlertTriangle className="mx-auto size-8 text-destructive" />
        <h2 className="mt-3 text-lg font-semibold">This page ran into a problem</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Your data is safe. Try again, or open another page from the menu.
        </p>
        <p className="mt-3 font-mono text-xs break-words text-muted-foreground">{this.state.error.message}</p>
        <Button className="mt-4" variant="outline" onClick={() => this.setState({ error: null })}>
          <RotateCcw /> Try again
        </Button>
      </div>
    )
  }
}
