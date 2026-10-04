import { useChatStore } from './chatStore'
import { useFolderStore } from './folderStore'
import { useNoteStore } from './noteStore'
import { useTagStore } from './tagStore'
import { useSettingsStore } from './settingsStore'
import { useAvatarStore } from './avatarStore'
import { useThemeStore } from './themeStore'

export function resetUserState() {
  useNoteStore.getState().reset()
  useChatStore.getState().reset()
  useFolderStore.getState().reset()
  useTagStore.getState().reset()
  useSettingsStore.getState().reset()
  useAvatarStore.getState().reset()
  useThemeStore.getState().reset()
}
