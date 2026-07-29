const paths = {
  search: <><circle cx="11" cy="11" r="6" /><path strokeLinecap="round" d="m16 16 4 4" /></>,
  plus: <path strokeLinecap="round" d="M12 5v14m7-7H5" />,
  pin: <path strokeLinecap="round" strokeLinejoin="round" d="M9 4h6l-1 6 3 3v1H7v-1l3-3-1-6zm3 10v6" />,
  trash: <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.9 12a2 2 0 01-2 2H7.9a2 2 0 01-2-2L5 7m5 4v6m4-6v6m1-10V4h-6v3M4 7h16" />,
  note: <path strokeLinecap="round" strokeLinejoin="round" d="M8 6h8M8 10h8M8 14h5m5 7H6a2 2 0 01-2-2V5a2 2 0 012-2h8l4 4v10a2 2 0 01-2 2z" />,
  back: <path strokeLinecap="round" strokeLinejoin="round" d="m15 18-6-6 6-6" />,
}

export default function NoteIcon({ name, className = 'h-4 w-4' }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  )
}
