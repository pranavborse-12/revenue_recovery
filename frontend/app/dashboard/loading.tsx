export default function DashboardLoading() {
  return (
    <div className="space-y-6 animate-pulse" aria-label="Loading dashboard">
      <div className="space-y-3">
        <div className="h-3 w-28 rounded bg-emerald-100" />
        <div className="h-8 w-64 rounded-lg bg-slate-200" />
        <div className="h-4 w-96 max-w-full rounded bg-slate-100" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((item) => <div key={item} className="h-36 rounded-2xl border border-slate-100 bg-white" />)}
      </div>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="h-[440px] rounded-2xl border border-slate-100 bg-white" />
        <div className="h-72 rounded-2xl bg-slate-900" />
      </div>
    </div>
  );
}
