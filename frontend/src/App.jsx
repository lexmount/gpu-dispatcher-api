import React, { useState, useRef, useEffect } from 'react'
import axios from 'axios'
import {
  UploadCloud,
  Rocket,
  Cpu,
  Activity,
  ShieldAlert,
  Power,
  BookOpen,
  Terminal,
  Layers,
  Server,
} from 'lucide-react'

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')
const CURRENT_USER = import.meta.env.VITE_CURRENT_USER ?? 'feng-test'

function apiDetail(err) {
  const d = err.response?.data?.detail
  if (d == null) return err.message
  return typeof d === 'string' ? d : JSON.stringify(d)
}

function formatDuration(iso) {
  if (!iso) return '—'
  try {
    const t = new Date(iso)
    if (Number.isNaN(t.getTime())) return '—'
    const sec = Math.max(0, Math.floor((Date.now() - t.getTime()) / 1000))
    const h = Math.floor(sec / 3600)
    const m = Math.floor((sec % 3600) / 60)
    const s = sec % 60
    if (h) return `${h}h ${m}m`
    if (m) return `${m}m ${s}s`
    return `${s}s`
  } catch {
    return '—'
  }
}

export default function SageProxyOS() {
  const [view, setView] = useState('user')

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 font-sans selection:bg-cyan-500/30">
      <nav className="border-b border-slate-800/80 bg-slate-900/50 backdrop-blur-md px-6 py-4 flex justify-between items-center sticky top-0 z-50">
        <div className="flex items-center space-x-3">
          <Cpu className="w-8 h-8 text-cyan-400 animate-pulse" />
          <h1 className="text-2xl font-black tracking-wider bg-gradient-to-r from-cyan-400 to-purple-500 bg-clip-text text-transparent">
            SageProxy OS
          </h1>
        </div>

        <div className="flex bg-slate-800 p-1 rounded-lg border border-slate-700 shadow-inner">
          <button
            type="button"
            onClick={() => setView('user')}
            className={`px-5 py-2 rounded-md text-sm font-bold transition-all ${view === 'user' ? 'bg-cyan-500 text-slate-950 shadow-[0_0_15px_rgba(6,182,212,0.5)]' : 'text-slate-400 hover:text-cyan-300'}`}
          >
            开发者终端
          </button>
          <button
            type="button"
            onClick={() => setView('admin')}
            className={`px-5 py-2 rounded-md text-sm font-bold transition-all ${view === 'admin' ? 'bg-purple-500 text-slate-950 shadow-[0_0_15px_rgba(168,85,247,0.5)]' : 'text-slate-400 hover:text-purple-300'}`}
          >
            资源与运维
          </button>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto p-6 md:p-8">
        {view === 'user' ? <UserPortal /> : <AdminCore />}
      </main>
    </div>
  )
}

function UserPortal() {
  const [file, setFile] = useState(null)
  const [isUploading, setIsUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [statusMsg, setStatusMsg] = useState('')
  const fileInputRef = useRef(null)

  const handleLaunch = async () => {
    if (!file) return
    setIsUploading(true)
    setProgress(0)
    setStatusMsg('1/3 建立云端安全通道...')

    try {
      const credRes = await axios.post(`${API_BASE}/generate-upload-url`, {
        file_name: file.name,
        user_id: CURRENT_USER,
      })

      setStatusMsg('2/3 加速推送数据包至云端...')
      await axios.put(credRes.data.upload_url, file, {
        headers: { 'Content-Type': file.type || 'application/x-gzip' },
        onUploadProgress: (evt) => {
          if (evt.total) setProgress(Math.round((evt.loaded * 100) / evt.total))
        },
      })

      setStatusMsg('3/3 请求调度 SageMaker 训练实例...')
      const submitRes = await axios.post(`${API_BASE}/submit-job`, {
        user_id: CURRENT_USER,
        script_s3_uri: credRes.data.s3_uri,
        job_name_prefix: 'web-job',
      })

      setStatusMsg(`✅ 已提交训练任务。Job 名称: ${submitRes.data.job_name}`)
    } catch (err) {
      setStatusMsg(`❌ 链路失败: ${apiDetail(err)}`)
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="animate-fade-in grid grid-cols-1 lg:grid-cols-2 gap-8 items-start mt-4">
      {/* 左侧：说明 + 示例 */}
      <div className="space-y-6">
        <div className="rounded-2xl border border-slate-700/80 bg-slate-900/40 p-6">
          <div className="flex items-center gap-2 text-cyan-400 font-bold text-lg mb-3">
            <BookOpen className="w-6 h-6" />
            这里是做什么的？
          </div>
          <p className="text-slate-300 text-sm leading-relaxed mb-4">
            把你在本机写好的<strong className="text-slate-100">训练代码目录</strong>
            打成 <code className="text-cyan-300 bg-slate-800 px-1 rounded">.tar.gz</code>
            ，经浏览器<strong>直传到 S3</strong>（不经过我们应用服务器带宽），再由后端在 AWS
            SageMaker 上<strong>拉起训练实例</strong>执行。适合快速试跑脚本、小体量数据；大模型权重请用 S3
            其它路径或单独管线同步。
          </p>
          <ul className="text-slate-400 text-sm space-y-2 list-disc pl-5">
            <li>入口脚本须命名为 <code className="text-cyan-200">train.py</code>（与后端环境变量一致）。</li>
            <li>打包内容解压后应在<strong>根目录</strong>能看到 <code className="text-cyan-200">train.py</code>。</li>
            <li>任务名会带你的用户 ID（当前为 <code className="text-amber-200/90">{CURRENT_USER}</code>），便于在运维侧区分。</li>
          </ul>
        </div>

        <div className="rounded-2xl border border-cyan-500/20 bg-slate-900/50 p-6">
          <div className="flex items-center gap-2 text-cyan-400 font-bold mb-3">
            <Layers className="w-5 h-5" />
            打包里应该有什么？（示例）
          </div>
          <p className="text-slate-400 text-xs mb-3">在训练项目根目录执行打包，保证解压后结构类似：</p>
          <pre className="text-xs font-mono text-left bg-slate-950/80 border border-slate-700 rounded-lg p-4 text-emerald-300/90 overflow-x-auto leading-relaxed">
{`my-project/
├── train.py          # 必填：训练入口
├── requirements.txt  # 可选：若镜像需额外 pip 依赖
├── data/
│   └── sample.csv
└── utils/
    └── model.py`}
          </pre>
          <p className="text-slate-500 text-xs mt-3">
            本地打包示例（在项目根目录）：
            <code className="block mt-2 text-slate-300 bg-slate-800/80 p-2 rounded">
              tar -czvf code.tar.gz train.py requirements.txt data utils
            </code>
          </p>
          <p className="text-slate-500 text-xs mt-2 flex items-start gap-2">
            <Terminal className="w-4 h-4 shrink-0 mt-0.5 text-slate-500" />
            也可使用仓库内 <code className="text-slate-400">sagecli submit</code> 在终端一键打包并提交（与网页等价链路）。
          </p>
        </div>
      </div>

      {/* 右侧：上传 */}
      <div className="w-full bg-slate-900/60 backdrop-blur-xl border border-cyan-500/30 rounded-2xl p-8 shadow-[0_0_40px_rgba(6,182,212,0.1)]">
        <h2 className="text-xl font-bold mb-2 text-cyan-400">上传代码包并提交任务</h2>
        <p className="text-slate-400 text-sm mb-6">
          仅支持 <strong className="text-slate-300">.tar.gz / .tgz</strong>。选择你在上一步打好的压缩包。
        </p>

        <div
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && !isUploading && fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            const f = e.dataTransfer.files[0]
            if (f) setFile(f)
          }}
          onClick={() => !isUploading && fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-10 flex flex-col items-center justify-center transition-all cursor-pointer ${file ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-700 hover:border-cyan-400/50'}`}
        >
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            accept=".tar.gz,.tgz,application/gzip"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <UploadCloud className={`w-12 h-12 mb-4 ${file ? 'text-cyan-400' : 'text-slate-500'}`} />
          <p className="text-lg text-slate-300 text-center">
            {file ? file.name : '点击或拖拽 code.tar.gz 到此处'}
          </p>
        </div>

        {progress > 0 && progress < 100 && (
          <div className="mt-6 w-full bg-slate-800 h-2 rounded-full overflow-hidden shadow-[0_0_10px_rgba(6,182,212,0.5)]">
            <div className="bg-cyan-400 h-full transition-all" style={{ width: `${progress}%` }} />
          </div>
        )}
        {statusMsg && (
          <p className="mt-4 text-center text-sm font-mono text-cyan-300 whitespace-pre-wrap">{statusMsg}</p>
        )}

        <button
          type="button"
          onClick={handleLaunch}
          disabled={!file || isUploading}
          className="mt-8 w-full flex items-center justify-center py-4 rounded-xl font-bold text-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 disabled:opacity-50 transition-all shadow-[0_0_20px_rgba(6,182,212,0.4)]"
        >
          <Rocket className="w-6 h-6 mr-2" />
          {isUploading ? '上传与调度中…' : '上传到 S3 并提交训练'}
        </button>
      </div>
    </div>
  )
}

function AdminCore() {
  const [stats, setStats] = useState({
    active_count: 0,
    total_training_instances: 0,
    total_gpu_units: 0,
    jobs_created_today_utc: 0,
    jobs: [],
    resource_note: '',
  })

  const fetchStats = async () => {
    try {
      const res = await axios.get(`${API_BASE}/admin/stats`)
      setStats(res.data)
    } catch (err) {
      console.error('抓取大盘数据失败', err)
    }
  }

  const forceKill = async (jobName) => {
    if (!window.confirm(`⚠️ 将强制终止训练任务（停止计费）：\n${jobName}\n\n确认继续？`)) return
    try {
      const enc = encodeURIComponent(jobName)
      await axios.post(`${API_BASE}/stop-job/${enc}`)
      window.alert('已发送停止指令，实例释放需要数十秒～数分钟，列表会自动刷新。')
      fetchStats()
    } catch (err) {
      window.alert(`终止失败: ${apiDetail(err)}`)
    }
  }

  useEffect(() => {
    fetchStats()
    const timer = setInterval(fetchStats, 10000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="animate-fade-in space-y-6">
      <div className="rounded-xl border border-purple-500/20 bg-slate-900/50 p-5">
        <h2 className="text-lg font-bold text-purple-300 mb-2 flex items-center gap-2">
          <Server className="w-5 h-5" />
          资源与运维视图
        </h2>
        <p className="text-slate-400 text-sm leading-relaxed">
          查看当前账户下<strong className="text-slate-200">进行中</strong>的 SageMaker 训练任务，以及池内占用的
          <strong className="text-slate-200">训练节点</strong>与<strong className="text-slate-200">GPU 规模（估算）</strong>
          。下方「GPU」由实例类型映射得出，用于容量感知；计费以 AWS 账单为准。
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-purple-500/35 p-5 rounded-xl shadow-[0_0_20px_rgba(168,85,247,0.08)]">
          <div className="flex items-start gap-3">
            <Activity className="w-10 h-10 text-purple-400 shrink-0" />
            <div>
              <p className="text-slate-400 text-xs uppercase tracking-wide">池中 GPU（估算）</p>
              <p className="text-3xl font-black text-white mt-1">{stats.total_gpu_units ?? 0}</p>
              <p className="text-slate-500 text-xs mt-2">所有进行中任务占用的加速卡张数之和</p>
            </div>
          </div>
        </div>
        <div className="bg-slate-900 border border-cyan-500/30 p-5 rounded-xl">
          <div className="flex items-start gap-3">
            <Cpu className="w-10 h-10 text-cyan-400 shrink-0" />
            <div>
              <p className="text-slate-400 text-xs uppercase tracking-wide">训练节点数</p>
              <p className="text-3xl font-black text-white mt-1">{stats.total_training_instances ?? 0}</p>
              <p className="text-slate-500 text-xs mt-2">SageMaker 训练作业配置的实例台数加总</p>
            </div>
          </div>
        </div>
        <div className="bg-slate-900 border border-slate-700 p-5 rounded-xl">
          <div className="flex items-start gap-3">
            <Layers className="w-10 h-10 text-slate-400 shrink-0" />
            <div>
              <p className="text-slate-400 text-xs uppercase tracking-wide">进行中任务数</p>
              <p className="text-3xl font-black text-white mt-1">{stats.active_count ?? 0}</p>
              <p className="text-slate-500 text-xs mt-2">状态为 InProgress 的训练作业数量</p>
            </div>
          </div>
        </div>
        <div className="bg-slate-900 border border-slate-700 p-5 rounded-xl">
          <div className="flex items-start gap-3">
            <ShieldAlert className="w-10 h-10 text-amber-500/80 shrink-0" />
            <div>
              <p className="text-slate-400 text-xs uppercase tracking-wide">今日新建任务 (UTC)</p>
              <p className="text-3xl font-black text-white mt-1">{stats.jobs_created_today_utc ?? 0}</p>
              <p className="text-slate-500 text-xs mt-2">自 UTC 0 点起创建过的训练作业（含已结束）</p>
            </div>
          </div>
        </div>
      </div>

      {stats.resource_note && (
        <p className="text-slate-500 text-xs border-l-2 border-slate-600 pl-3">{stats.resource_note}</p>
      )}

      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 bg-slate-800/50 flex flex-wrap justify-between gap-2 items-center">
          <h3 className="font-bold text-slate-200">进行中任务明细</h3>
          <span className="text-slate-500 text-xs font-mono">
            每 10s 刷新 · {stats.as_of_utc ? new Date(stats.as_of_utc).toLocaleString() : '—'}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[900px]">
            <thead>
              <tr className="bg-slate-900 text-slate-400 text-xs uppercase tracking-wide border-b border-slate-800">
                <th className="p-3">任务 ID</th>
                <th className="p-3">用户</th>
                <th className="p-3">实例类型</th>
                <th className="p-3 text-center">节点</th>
                <th className="p-3 text-center">GPU(估)</th>
                <th className="p-3">已运行</th>
                <th className="p-3">状态</th>
                <th className="p-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {stats.jobs.length === 0 ? (
                <tr>
                  <td colSpan="8" className="p-10 text-center text-slate-500">
                    当前没有进行中的训练任务，池中无占用。
                  </td>
                </tr>
              ) : (
                stats.jobs.map((job) => (
                  <tr
                    key={job.job_name}
                    className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors text-sm"
                  >
                    <td className="p-3 font-mono text-cyan-300/90 break-all max-w-[220px]">{job.job_name}</td>
                    <td className="p-3 text-slate-300">{job.user_id || '—'}</td>
                    <td className="p-3 text-slate-400 font-mono text-xs">{job.instance_type ?? '—'}</td>
                    <td className="p-3 text-center text-slate-200">{job.instance_count ?? '—'}</td>
                    <td className="p-3 text-center text-amber-200/90 font-semibold">{job.gpu_units ?? '—'}</td>
                    <td className="p-3 text-slate-400 whitespace-nowrap">{formatDuration(job.creation_time)}</td>
                    <td className="p-3">
                      <span className="px-2 py-1 rounded-full text-xs font-bold bg-green-500/15 text-green-400 border border-green-500/25 inline-flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                        {job.status}
                      </span>
                    </td>
                    <td className="p-3 text-right">
                      <button
                        type="button"
                        onClick={() => forceKill(job.job_name)}
                        className="inline-flex items-center px-3 py-1.5 bg-red-950/50 text-red-400 hover:bg-red-900/60 border border-red-500/30 rounded-md text-xs font-bold"
                      >
                        <Power className="w-3.5 h-3.5 mr-1.5" /> 停止
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
