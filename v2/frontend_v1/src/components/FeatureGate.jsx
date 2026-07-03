import { useFeatureFlagStore } from '@/stores/featureFlagStore'

export default function FeatureGate({ flag, children }) {
  const isEnabled = useFeatureFlagStore((s) => s.isEnabled)
  const loaded = useFeatureFlagStore((s) => s.loaded)

  if (!loaded) return null

  if (!isEnabled(flag)) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-2">
          <p className="text-zinc-500 dark:text-zinc-400 text-sm font-medium">
            This feature is not available yet
          </p>
          <p className="text-zinc-400 dark:text-zinc-600 text-xs">
            Check back later — it may be under development.
          </p>
        </div>
      </div>
    )
  }

  return children
}
