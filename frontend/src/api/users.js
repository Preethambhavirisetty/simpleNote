import client from './client'

export const usersApi = {
  // Own profile
  getMe: () => client.get('/api/users/me'),
  updateMe: (data) => client.patch('/api/users/me', data),
  deleteMe: () => client.delete('/api/users/me'),

  // Admin-only
  listUsers: (params) => client.get('/api/users/', { params }),
  getUser: (userId) => client.get(`/api/users/${userId}`),
  updateUser: (userId, data) => client.patch(`/api/users/${userId}`, data),
  deleteUser: (userId) => client.delete(`/api/users/${userId}`),
  assignRoles: (userId, data) => client.patch(`/api/users/${userId}/roles`, data),
  activateUser: (userId) => client.patch(`/api/users/${userId}/activate`),
  deactivateUser: (userId) => client.patch(`/api/users/${userId}/deactivate`),
}
