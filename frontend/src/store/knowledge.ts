import { create } from 'zustand'
import { knowledgeApi, type DocumentPayload, type SpacePayload } from '../api/knowledge'
import type { Document, KnowledgeSpace } from '../types'

interface KnowledgeState {
  spaces: KnowledgeSpace[]
  spacesLoading: boolean
  documents: Document[]
  documentsLoading: boolean

  fetchSpaces: () => Promise<void>
  createSpace: (data: SpacePayload) => Promise<KnowledgeSpace>
  updateSpace: (spaceId: string, data: Partial<SpacePayload>) => Promise<void>
  deleteSpace: (spaceId: string) => Promise<void>

  fetchDocuments: (spaceId: string) => Promise<void>
  updateDocument: (spaceId: string, docId: string, data: Partial<DocumentPayload>) => Promise<void>
  deleteDocument: (spaceId: string, docId: string) => Promise<void>
}

export const useKnowledgeStore = create<KnowledgeState>((set) => ({
  spaces: [],
  spacesLoading: false,
  documents: [],
  documentsLoading: false,

  fetchSpaces: async () => {
    set({ spacesLoading: true })
    try {
      const res = await knowledgeApi.listSpaces()
      set({ spaces: res.spaces })
    } finally {
      set({ spacesLoading: false })
    }
  },

  createSpace: async (data) => {
    const space = await knowledgeApi.createSpace(data)
    const res = await knowledgeApi.listSpaces()
    set({ spaces: res.spaces })
    return space
  },

  updateSpace: async (spaceId, data) => {
    await knowledgeApi.updateSpace(spaceId, data)
    const res = await knowledgeApi.listSpaces()
    set({ spaces: res.spaces })
  },

  deleteSpace: async (spaceId) => {
    await knowledgeApi.deleteSpace(spaceId)
    const res = await knowledgeApi.listSpaces()
    set({ spaces: res.spaces, documents: [] })
  },

  fetchDocuments: async (spaceId) => {
    set({ documentsLoading: true })
    try {
      const res = await knowledgeApi.listDocuments(spaceId)
      set({ documents: res.documents })
    } finally {
      set({ documentsLoading: false })
    }
  },

  updateDocument: async (spaceId, docId, data) => {
    await knowledgeApi.updateDocument(spaceId, docId, data)
    const res = await knowledgeApi.listDocuments(spaceId)
    set({ documents: res.documents })
  },

  deleteDocument: async (spaceId, docId) => {
    await knowledgeApi.deleteDocument(spaceId, docId)
    const res = await knowledgeApi.listDocuments(spaceId)
    set({ documents: res.documents })
  },
}))