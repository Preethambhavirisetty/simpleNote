import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const MAX_AVATAR_DATA_URL_BYTES = 256 * 1024

const defaultAvatar = () => ({ type: 'character', value: 0 })

const sanitizeAvatar = (avatar) => {
  if (
    avatar?.type === 'character' &&
    Number.isInteger(avatar.value) &&
    avatar.value >= 0
  ) {
    return avatar
  }

  if (
    avatar?.type === 'image' &&
    typeof avatar.value === 'string' &&
    /^data:image\/(?:png|jpeg|webp|gif);base64,/.test(avatar.value) &&
    avatar.value.length <= MAX_AVATAR_DATA_URL_BYTES
  ) {
    return avatar
  }

  return defaultAvatar()
}

export const useAvatarStore = create(
  persist(
    (set) => ({
      avatar: defaultAvatar(),
      setCharacter: (value) => set({ avatar: { type: 'character', value } }),
      setImage: (value) => {
        const avatar = sanitizeAvatar({ type: 'image', value })
        if (avatar.type !== 'image') return false

        set({ avatar })
        return true
      },
      reset: () => set({ avatar: defaultAvatar() }),
    }),
    {
      name: 'notelite-avatar',
      version: 2,
      migrate: (persisted) => ({
        ...(persisted ?? {}),
        avatar: sanitizeAvatar(persisted?.avatar),
      }),
      partialize: (state) => ({ avatar: sanitizeAvatar(state.avatar) }),
    },
  ),
)
