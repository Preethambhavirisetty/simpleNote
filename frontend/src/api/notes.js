import client from './client'

export const notesApi = {
  list: (params) => client.get('/api/notes/', { params }),
  create: (data) => client.post('/api/notes/', data),
  get: (noteId) => client.get(`/api/notes/${noteId}`),
  update: (noteId, data) => client.patch(`/api/notes/${noteId}`, data),
  move: (noteId, data) => client.patch(`/api/notes/${noteId}/move`, data),
  delete: (noteId) => client.delete(`/api/notes/${noteId}`),
  addTag: (noteId, tagId) => client.post(`/api/notes/${noteId}/tags/${tagId}`),
  removeTag: (noteId, tagId) => client.delete(`/api/notes/${noteId}/tags/${tagId}`),
}
