import client from './client'

export const tagsApi = {
  list: () => client.get('/api/tags/'),
  create: (data) => client.post('/api/tags/', data),
  get: (tagId) => client.get(`/api/tags/${tagId}`),
  update: (tagId, data) => client.patch(`/api/tags/${tagId}`, data),
  delete: (tagId) => client.delete(`/api/tags/${tagId}`),
}
