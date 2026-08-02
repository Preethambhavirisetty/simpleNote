import client from './client'

export const foldersApi = {
  list: (params) => client.get('/api/folders/', { params }),
  create: (data) => client.post('/api/folders/', data),
  get: (folderId) => client.get(`/api/folders/${folderId}`),
  update: (folderId, data) => client.patch(`/api/folders/${folderId}`, data),
  delete: (folderId) => client.delete(`/api/folders/${folderId}`),
}
