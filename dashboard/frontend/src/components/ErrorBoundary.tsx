import React from 'react'

interface Props {
    children: React.ReactNode
}

interface State {
    hasError: boolean
    error: Error | null
    errorInfo: React.ErrorInfo | null
}

export class ErrorBoundary extends React.Component<Props, State> {
    constructor(props: Props) {
        super(props)
        this.state = { hasError: false, error: null, errorInfo: null }
    }

    static getDerivedStateFromError(error: Error): Partial<State> {
        return { hasError: true, error }
    }

    componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
        console.error('React ErrorBoundary caught an error:', error, errorInfo)
        this.setState({ errorInfo })
    }

    render() {
        if (this.state.hasError) {
            return (
                <div style={{
                    padding: '40px',
                    backgroundColor: '#1a1d21',
                    color: '#e1e4e8',
                    minHeight: '100vh',
                    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
                }}>
                    <h1 style={{ color: '#ef4444', marginBottom: '20px' }}>
                        ⚠️ Dashboard Error
                    </h1>
                    <p style={{ marginBottom: '20px', color: '#8b949e' }}>
                        Something went wrong while rendering the dashboard.
                        This is often caused by invalid data in the history records.
                    </p>

                    <div style={{
                        backgroundColor: '#21252b',
                        padding: '16px',
                        borderRadius: '8px',
                        marginBottom: '20px',
                        overflowX: 'auto'
                    }}>
                        <strong style={{ color: '#ff7b7b' }}>Error: </strong>
                        <pre style={{ color: '#ffc66d', margin: '10px 0' }}>
                            {this.state.error?.message}
                        </pre>
                        {this.state.error?.stack && (
                            <details>
                                <summary style={{ cursor: 'pointer', color: '#8b949e' }}>
                                    Stack trace
                                </summary>
                                <pre style={{ color: '#6e7681', fontSize: '12px', marginTop: '10px' }}>
                                    {this.state.error.stack}
                                </pre>
                            </details>
                        )}
                    </div>

                    <button
                        onClick={() => {
                            localStorage.clear()
                            window.location.reload()
                        }}
                        style={{
                            backgroundColor: '#238636',
                            color: 'white',
                            padding: '10px 20px',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: 'pointer',
                            marginRight: '10px'
                        }}
                    >
                        Clear Cache & Reload
                    </button>

                    <button
                        onClick={() => window.location.reload()}
                        style={{
                            backgroundColor: '#21262d',
                            color: '#c9d1d9',
                            padding: '10px 20px',
                            border: '1px solid #30363d',
                            borderRadius: '6px',
                            cursor: 'pointer'
                        }}
                    >
                        Reload Page
                    </button>
                </div>
            )
        }

        return this.props.children
    }
}
