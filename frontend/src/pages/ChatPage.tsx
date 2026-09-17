import { Bot, Loader2, MessageSquare, Plus, Send, Trash2, User } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { chatApi } from '../api/chat'
import { knowledgeApi } from '../api/knowledge'
import Modal from '../components/Modal'
import Select from '../components/Select'
import SourceList from '../components/SourceList'
import type { Citation, Conversation, KnowledgeSpace } from '../types'

interface UiMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  streaming?: boolean
}

const SELECTED_KEY = 'rag_chat_selected_conversation_id'
const SPACE_KEY = 'rag_chat_selected_space_id'

export default function ChatPage() {
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([])
  const [selectedSpaceId, setSelectedSpaceId] = useState<string>('')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<UiMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null)
  const [deleting, setDeleting] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    knowledgeApi.listSpaces().then((res) => {
      setSpaces(res.spaces)
      const saved = localStorage.getItem(SPACE_KEY)
      if (saved && res.spaces.some((s) => s.id === saved)) {
        setSelectedSpaceId(saved)
      } else {
        localStorage.removeItem(SPACE_KEY)
      }
    }).catch(() => { })
    refreshConversations(true)
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const refreshConversations = async (restore = false) => {
    try {
      const res = await chatApi.listConversations()
      setConversations(res.conversations)
      if (restore) {
        const saved = localStorage.getItem(SELECTED_KEY)
        if (saved && res.conversations.some((c) => c.id === saved)) {
          await selectConversation(saved)
        } else {
          localStorage.removeItem(SELECTED_KEY)
        }
      }
    } catch {
      /* ignore */
    }
  }

  const selectConversation = async (id: string) => {
    setSelectedConversationId(id)
    localStorage.setItem(SELECTED_KEY, id)
    try {
      const res = await chatApi.getMessages(id)
      setMessages(
        res.messages.map((m) => ({
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content,
          citations: m.citations ?? undefined,
        })),
      )
    } catch {
      setMessages([])
    }
  }

  const newConversation = () => {
    setSelectedConversationId(null)
    localStorage.removeItem(SELECTED_KEY)
    setMessages([])
  }

  const confirmDeleteConversation = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await chatApi.deleteConversation(deleteTarget.id)
      if (selectedConversationId === deleteTarget.id) newConversation()
      setDeleteTarget(null)
      refreshConversations()
    } catch {
      /* ignore */
    } finally {
      setDeleting(false)
    }
  }

  const handleSend = async (e: FormEvent) => {
    e.preventDefault()
    const question = input.trim()
    if (!question || streaming) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setStreaming(true)

    const assistantIndex = messages.length + 1
    setMessages((prev) => [...prev, { role: 'assistant', content: '', streaming: true }])

    try {
      await chatApi.ask(
        {
          question,
          space_id: selectedSpaceId || null,
          conversation_id: selectedConversationId,
        },
        (event) => {
          if (event.type === 'meta') {
            const data = event.data as { conversation_id?: string }
            if (data.conversation_id && !selectedConversationId) {
              setSelectedConversationId(data.conversation_id)
              localStorage.setItem(SELECTED_KEY, data.conversation_id)
            }
          } else if (event.type === 'citations') {
            const citations = event.data as Citation[]
            setMessages((prev) =>
              prev.map((m, i) => (i === assistantIndex ? { ...m, citations } : m)),
            )
          } else if (event.type === 'delta') {
            const delta = String(event.data)
            setMessages((prev) =>
              prev.map((m, i) => (i === assistantIndex ? { ...m, content: m.content + delta } : m)),
            )
          } else if (event.type === 'error') {
            const err = String(event.data)
            setMessages((prev) =>
              prev.map((m, i) =>
                i === assistantIndex && !m.content ? { ...m, content: `[错误] ${err}` } : m,
              ),
            )
          }
        },
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : '请求失败'
      setMessages((prev) =>
        prev.map((m, i) => (i === assistantIndex ? { ...m, content: `[错误] ${msg}` } : m)),
      )
    } finally {
      setMessages((prev) =>
        prev.map((m, i) => (i === assistantIndex ? { ...m, streaming: false } : m)),
      )
      setStreaming(false)
      refreshConversations()
    }
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-4">
      {/* 会话列表 */}
      <aside className="flex w-60 shrink-0 flex-col rounded-xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 p-3">
          <button
            type="button"
            onClick={newConversation}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            <Plus size={16} />
            新建会话
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`group flex cursor-pointer items-center justify-between rounded-lg px-2 py-2 text-sm ${selectedConversationId === c.id ? 'bg-indigo-50 text-indigo-700' : 'hover:bg-slate-50'
                }`}
              onClick={() => selectConversation(c.id)}
            >
              <div className="flex min-w-0 items-center gap-2">
                <MessageSquare size={14} className="shrink-0 opacity-60" />
                <span className="truncate">{c.title || '新会话'}</span>
              </div>
              <button
                type="button"
                className="hidden shrink-0 text-slate-400 hover:text-red-600 group-hover:block"
                onClick={(e) => {
                  e.stopPropagation()
                  setDeleteTarget(c)
                }}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          {conversations.length === 0 && (
            <p className="mt-4 text-center text-xs text-slate-400">暂无会话</p>
          )}
        </div>
      </aside>

      {/* 对话区 */}
      <section className="flex flex-1 flex-col rounded-xl border border-slate-200 bg-white">
        <header className="flex items-center gap-3 border-b border-slate-100 px-4 py-3">
          <label className="text-sm text-slate-600">知识空间</label>
          <Select
            value={selectedSpaceId}
            onChange={(value) => {
              setSelectedSpaceId(value)
              localStorage.setItem(SPACE_KEY, value)
            }}
            className="w-48"
            options={[
              { value: '', label: '通用回答' },
              ...spaces.map((s) => ({ value: s.id, label: s.name })),
            ]}
          />
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {messages.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center text-slate-400">
              <Bot size={36} className="mb-2 opacity-40" />
              <p className="text-sm">选择一个知识空间，开始基于私有知识的智能问答</p>
            </div>
          )}
          {messages.map((m, i) => (
            <MessageBubble key={i} message={m} />
          ))}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={handleSend} className="flex items-end gap-2 border-t border-slate-100 p-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入你的问题…"
            rows={1}
            className="max-h-32 flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend(e)
              }
            }}
          />
          <button
            type="submit"
            disabled={streaming || !input.trim()}
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {streaming ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          </button>
        </form>
      </section>

      {/* 删除会话确认 */}
      <Modal open={deleteTarget !== null} title="删除确认" onClose={() => setDeleteTarget(null)}>
        <div className="space-y-4">
          <p className="text-sm text-slate-700">
            确定删除会话「{deleteTarget?.title || '新会话'}」吗？此操作不可恢复。
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDeleteTarget(null)}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
            <button
              type="button"
              onClick={confirmDeleteConversation}
              disabled={deleting}
              className="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-60"
            >
              {deleting && <Loader2 size={14} className="animate-spin" />}
              确认删除
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

function ThinkingIndicator() {
  const chars = ['思', '考', '中', '.', '.', '.']
  return (
    <span className="inline-flex items-center text-slate-500" aria-label="思考中">
      {chars.map((ch, i) => (
        <span
          key={i}
          className="inline-block"
          style={{ animation: `wave-bounce 1.2s ease-in-out ${i * 0.12}s infinite` }}
        >
          {ch}
        </span>
      ))}
    </span>
  )
}

function MessageBubble({ message }: { message: UiMessage }) {
  const isUser = message.role === 'user'
  return (
    <div className={`mb-4 flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`flex max-w-[80%] gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
        <span
          className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white ${isUser ? 'bg-slate-500' : 'bg-indigo-600'
            }`}
        >
          {isUser ? <User size={14} /> : <Bot size={14} />}
        </span>
        <div>
          <div
            className={`rounded-xl px-3 py-2 text-sm leading-relaxed ${isUser ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-800'
              }`}
          >
            {isUser ? (
              <span className="whitespace-pre-wrap break-words">{message.content}</span>
            ) : message.content ? (
              <div className="markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
              </div>
            ) : (
              <ThinkingIndicator />
            )}
            {message.streaming && message.content && <span className="ml-0.5 inline-block animate-pulse">▍</span>}
          </div>
          <SourceList citations={message.citations} />
        </div>
      </div>
    </div>
  )
}