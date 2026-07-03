import client from './client'
import { unwrap, unwrapList } from '@/lib/api'

export const conversationsApi = {
  list: (params) => client.get('/api/conversations/', { params }).then((r) => unwrapList(r.data)),
  get: (id) => client.get(`/api/conversations/${id}`).then((r) => unwrap(r.data)),
  create: (data) => client.post('/api/conversations/', data).then((r) => unwrap(r.data)),
  delete: (id) => client.delete(`/api/conversations/${id}`),
}
