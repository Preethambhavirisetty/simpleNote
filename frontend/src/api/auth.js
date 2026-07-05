import client from './client'

export const authApi = {
  register: (data) => client.post('/api/auth/register', data),
  login: (data) => client.post('/api/auth/login', data),
  logout: () => client.delete('/api/auth/logout/'), // trailing slash required by BE
  changePassword: (data) => client.patch('/api/auth/change-password', data),
}
