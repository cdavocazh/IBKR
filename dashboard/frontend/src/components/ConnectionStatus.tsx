interface Props {
  connected: boolean
  lastUpdate: string | null
}

export function ConnectionStatus({ connected, lastUpdate }: Props) {
  const age = lastUpdate
    ? Math.round((Date.now() - new Date(lastUpdate).getTime()) / 1000)
    : null

  return (
    <div className="flex items-center gap-2 text-sm">
      <span
        className={`inline-block h-2.5 w-2.5 rounded-full ${
          connected
            ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.6)]'
            : 'bg-red-500'
        }`}
      />
      <span className="text-gray-300">
        {connected ? 'Connected to IBKR' : 'Disconnected'}
      </span>
      {age !== null && age < 300 && (
        <span className="text-gray-500">({age}s ago)</span>
      )}
    </div>
  )
}
