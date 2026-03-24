import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

const API_URL = 'http://localhost:8000'

const EXAMPLE_QUERIES = [
  "Find the Bill of Materials for MC2 OXO",
  "How many ECRs are in the system?",
  "Trace electrical leakage testing from risk to verification",
  "What changed between Rev A and Rev B of RSK-M02-017?",
  "Show me all risk-related documents",
  "What are the acceptance criteria for the electrical safety test?",
]

const TOOL_LABELS = {
  search_documents: "Searching documents",
  list_documents: "Listing documents",
  get_document_content: "Reading document",
  trace_references: "Tracing references",
  compare_revisions: "Comparing revisions",
}

function toolLabel(name, args) {
  const base = TOOL_LABELS[name] || name
  if (name === 'search_documents' && args?.query) return `Searching for "${args.query}"`
  if (name === 'list_documents' && args?.doc_type) return `Listing ${args.doc_type} documents`
  if (name === 'get_document_content' && args?.doc_id) return `Reading ${args.doc_id}`
  if (name === 'trace_references' && args?.doc_id) return `Tracing references for ${args.doc_id}`
  if (name === 'compare_revisions' && args?.doc_id) return `Comparing ${args.doc_id} Rev ${args.rev_a} vs Rev ${args.rev_b}`
  return base
}

function StepItem({ step }) {
  if (step.type === 'reasoning') {
    return (
      <div className="text-[13px] text-gray-400 italic leading-relaxed pl-1">
        {step.content.length > 200 ? step.content.slice(0, 200) + '...' : step.content}
      </div>
    )
  }

  if (step.type === 'tool_call') {
    return (
      <div className="space-y-0.5">
        <div className="flex items-center gap-2 text-[13px] text-gray-500">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" />
          <span>{toolLabel(step.name, step.args)}</span>
          {step.searching && (
            <span className="inline-flex gap-0.5 dot-pulse-inline">
              <span className="w-1 h-1 bg-gray-400 rounded-full" />
              <span className="w-1 h-1 bg-gray-400 rounded-full" />
              <span className="w-1 h-1 bg-gray-400 rounded-full" />
            </span>
          )}
        </div>
        {step.summary && (
          <div className="text-[12px] text-gray-400 pl-[18px]">{step.summary}</div>
        )}
      </div>
    )
  }

  return null
}

function SourceChips({ docs }) {
  if (!docs || docs.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1.5 pt-3 mt-3 border-t border-gray-100">
      <span className="text-[12px] text-gray-400 mr-0.5 self-center">Sources:</span>
      {docs.map((doc, i) => (
        <span
          key={i}
          className="text-[11px] font-mono bg-blue-50 text-blue-600 rounded px-1.5 py-0.5 border border-blue-100"
        >
          {doc}
        </span>
      ))}
    </div>
  )
}

function ThinkingPulse() {
  return (
    <div className="flex items-center gap-2 text-[13px] text-gray-400 pl-1">
      <span className="inline-flex gap-0.5 dot-pulse-inline">
        <span className="w-1.5 h-1.5 bg-gray-300 rounded-full" />
        <span className="w-1.5 h-1.5 bg-gray-300 rounded-full" />
        <span className="w-1.5 h-1.5 bg-gray-300 rounded-full" />
      </span>
      <span className="text-gray-400">Thinking</span>
    </div>
  )
}

function AssistantMessage({ msg, isStreaming }) {
  const hasSteps = msg.steps && msg.steps.length > 0
  const hasAnswer = msg.answer && msg.answer.length > 0
  const showPulse = isStreaming && !hasAnswer && !hasSteps

  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] space-y-3 w-full">
        {showPulse && <ThinkingPulse />}

        {hasSteps && (
          <div className="space-y-1.5 py-1">
            {msg.steps.map((step, i) => (
              <StepItem key={i} step={step} />
            ))}
          </div>
        )}

        {hasAnswer && (
          <div className="bg-white rounded-xl border border-gray-200/80 px-5 py-4 shadow-xs">
            <div className="prose prose-sm prose-gray max-w-none prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-p:my-1.5 prose-p:leading-relaxed prose-li:my-0.5 prose-table:text-[13px] prose-code:text-[13px] prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {msg.answer}
              </ReactMarkdown>
            </div>
            <SourceChips docs={msg.sources} />
          </div>
        )}
      </div>
    </div>
  )
}

function UserMessage({ content }) {
  return (
    <div className="flex justify-end">
      <div className="bg-gray-900 text-white rounded-2xl px-4 py-2.5 max-w-[75%]">
        <p className="text-[14px] leading-relaxed whitespace-pre-wrap">{content}</p>
      </div>
    </div>
  )
}

export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [streamingMsg, setStreamingMsg] = useState(null)
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const chatHistory = useRef([])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingMsg, loading])

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px'
    }
  }, [input])

  async function sendMessage(text) {
    const content = (text || input).trim()
    if (!content || loading) return

    setInput('')
    setLoading(true)

    const userMsg = { role: 'user', content }
    chatHistory.current = [...chatHistory.current, userMsg]
    setMessages(prev => [...prev, { role: 'user', content }])

    const current = {
      role: 'assistant',
      steps: [],
      answer: '',
      sources: [],
    }
    setStreamingMsg({ ...current })

    try {
      const res = await fetch(`${API_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: chatHistory.current }),
      })

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6))

          switch (data.type) {
            case 'reasoning':
              current.steps.push({ type: 'reasoning', content: data.content })
              break
            case 'tool_call':
              current.steps.push({
                type: 'tool_call',
                name: data.name,
                args: data.args,
                summary: null,
                searching: true,
              })
              break
            case 'tool_result':
              for (let i = current.steps.length - 1; i >= 0; i--) {
                const s = current.steps[i]
                if (s.type === 'tool_call' && s.name === data.name && s.searching) {
                  s.summary = data.summary
                  s.searching = false
                  break
                }
              }
              break
            case 'answer':
              current.answer = data.content
              break
            case 'sources':
              current.sources = data.docs
              break
            case 'done':
              current.steps.forEach(s => { if (s.searching) s.searching = false })
              break
          }

          setStreamingMsg({ ...current, steps: [...current.steps] })
        }
      }

      chatHistory.current = [
        ...chatHistory.current,
        { role: 'assistant', content: current.answer },
      ]
      setMessages(prev => [...prev, { ...current, role: 'assistant' }])

    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        steps: [],
        answer: `Error: ${err.message}`,
        sources: [],
      }])
    } finally {
      setStreamingMsg(null)
      setLoading(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  function newConversation() {
    chatHistory.current = []
    setMessages([])
    setStreamingMsg(null)
    setLoading(false)
    setInput('')
  }

  const isEmpty = messages.length === 0 && !streamingMsg

  return (
    <div className="h-screen flex flex-col bg-[#fafafa]">
      <header className="shrink-0 border-b border-gray-200 bg-white">
        <div className="max-w-3xl mx-auto px-4 h-14 flex items-center justify-between">
          <h1 className="text-[15px] font-semibold text-gray-900 tracking-tight">QMS Document Search</h1>
          {messages.length > 0 && (
            <button
              onClick={newConversation}
              className="text-[12px] text-gray-500 hover:text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg px-3 py-1.5 transition-colors cursor-pointer font-medium"
            >
              New conversation
            </button>
          )}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6">
          {isEmpty ? (
            <div className="flex flex-col items-center justify-center pt-24">
              <h2 className="text-[17px] font-semibold text-gray-900 mb-1.5 tracking-tight">QMS Document Search</h2>
              <p className="text-[13px] text-gray-500 mb-8 text-center max-w-md leading-relaxed">
                Search, analyze, and cross-reference documents from the MC2 OXO Quality Management System.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
                {EXAMPLE_QUERIES.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => sendMessage(q)}
                    className="text-left text-[13px] text-gray-600 bg-white border border-gray-200 rounded-xl px-4 py-3 hover:bg-gray-50 hover:border-gray-300 transition-all cursor-pointer leading-relaxed"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              {messages.map((msg, i) =>
                msg.role === 'user'
                  ? <UserMessage key={i} content={msg.content} />
                  : <AssistantMessage key={i} msg={msg} />
              )}
              {streamingMsg && <AssistantMessage msg={streamingMsg} isStreaming />}
              <div ref={bottomRef} />
            </div>
          )}
        </div>
      </main>

      <footer className="shrink-0 border-t border-gray-200 bg-white">
        <div className="max-w-3xl mx-auto px-4 py-3">
          <div className="flex items-end gap-2 bg-gray-50 border border-gray-200 rounded-xl px-3 py-2 focus-within:border-gray-400 focus-within:ring-1 focus-within:ring-gray-300 transition-all">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about QMS documents..."
              className="flex-1 bg-transparent text-[14px] text-gray-900 placeholder-gray-400 resize-none outline-none min-h-[24px] max-h-[120px] leading-6"
              rows={1}
              disabled={loading}
            />
            <button
              onClick={() => sendMessage()}
              disabled={loading || !input.trim()}
              className="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg bg-gray-900 text-white disabled:opacity-20 disabled:cursor-not-allowed hover:bg-gray-700 transition-colors cursor-pointer"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M3 8L8 3M8 3L13 8M8 3V13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          </div>
        </div>
      </footer>
    </div>
  )
}
