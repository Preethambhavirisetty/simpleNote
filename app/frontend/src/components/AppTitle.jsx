import noteliteIcon from '@/assets/notelite_icon.png'

const sizes = {
  icon: { root: 'app-title-icon-only', icon: 'app-title-icon-sm', text: 'sr-only' },
  sm: { root: 'app-title-sm', icon: 'app-title-icon-sm', text: 'app-title-text-sm' },
  md: { root: 'app-title-md', icon: 'app-title-icon-md', text: 'app-title-text-md' },
  lg: { root: 'app-title-lg', icon: 'app-title-icon-lg', text: 'app-title-text-lg' },
}

const AppTitle = ({ size = 'md', showText = true, className = '' }) => {
  const variant = sizes[size] ?? sizes.md
  const rootClass = ['app-title', variant.root, className].filter(Boolean).join(' ')
  const textClass = showText ? ['app-title-text', variant.text].join(' ') : 'sr-only'

  return (
    <span className={rootClass}>
      <img src={noteliteIcon} alt="" className={['app-title-icon', variant.icon].join(' ')} />
      <span className={textClass}>NoteLite</span>
    </span>
  )
}

export { AppTitle }
