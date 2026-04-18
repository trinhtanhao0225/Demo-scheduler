import React, { useState } from 'react';
import axios from 'axios';
import { 
  DndContext, 
  closestCenter, 
  PointerSensor, 
  useSensor, 
  useSensors, 
  DragOverlay 
} from '@dnd-kit/core';
import { 
  SortableContext, 
  horizontalListSortingStrategy, 
  useSortable 
} from '@dnd-kit/sortable';
import { useDroppable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';

const API_URL = 'http://127.0.0.1:8000';

const fakeData = {
  employees: [
    { id: "N1", name: "Alice Nguyen", role: "Nurse", is_senior: true, weekly_max_hours: 40 },
    { id: "N2", name: "Bob Tran", role: "Nurse", is_senior: true, weekly_max_hours: 40 },
    { id: "N3", name: "Catherine Le", role: "Nurse", is_senior: true, weekly_max_hours: 40 },
    { id: "N4", name: "Diana Pham", role: "Nurse", is_senior: false, weekly_max_hours: 40 },
    { id: "C1", name: "Grace Vu", role: "Caregiver", is_senior: true, weekly_max_hours: 40 },
  ],
  num_days: 7,
  min_staff: { M: 2, E: 2, N: 1 },
};

// ================= COMPONENTS =================
function EmployeeItem({ emp, isOverlay = false }) {
  const { attributes, listeners, setNodeRef, transform } = useSortable({ 
    id: emp.id, 
    data: { employee: emp } 
  });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform) }}
      {...attributes}
      {...listeners}
      className={`p-3 rounded-xl border bg-white shadow-sm cursor-grab active:cursor-grabbing transition-all min-w-[160px]
        ${isOverlay ? 'border-blue-600 shadow-xl scale-105' : 'border-slate-200 hover:border-blue-300 hover:shadow-md'}`}
    >
      <div className="flex items-center justify-between">
        <p className="font-bold text-sm text-slate-700">
          {emp.is_senior && "⭐ "}{emp.name}
        </p>
        <span className="text-[10px] bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full font-bold">
          {emp.weekly_max_hours}h
        </span>
      </div>
      <p className="text-xs text-slate-400 mt-0.5 uppercase tracking-tighter font-semibold">{emp.role}</p>
    </div>
  );
}

function ShiftSlot({ dayIdx, shift, assigned, onRemove }) {
  const { setNodeRef, isOver } = useDroppable({ 
    id: `slot-${dayIdx}-${shift}`, 
    data: { dayIdx, shift } 
  });

  const shiftNames = { M: "Morning", E: "Evening", N: "Night" };

  return (
    <div
      ref={setNodeRef}
      className={`min-h-[140px] p-3 rounded-xl border-2 transition-all flex flex-col gap-2
        ${isOver ? 'bg-blue-50 border-blue-400 border-solid' : 'bg-slate-50/50 border-slate-100 border-dashed'}`}
    >
      <p className="uppercase text-[10px] font-black text-slate-400 tracking-widest">{shiftNames[shift]}</p>
      
      <div className="flex flex-col gap-1.5">
        {assigned.map((e) => (
          <div
            key={e.id}
            className="bg-white border border-slate-200 p-2 rounded-lg flex justify-between items-center group shadow-sm"
          >
            <div className="flex items-center gap-1.5 overflow-hidden">
              <span className="font-semibold text-[11px] text-slate-700 truncate">{e.name}</span>
              {e.is_senior && <span className="text-[10px]">⭐</span>}
            </div>
            <button
              onClick={() => onRemove(dayIdx, shift, e.id)}
              className="text-rose-400 hover:text-rose-600 transition-colors ml-1"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ================= MAIN APP =================
export default function App() {
  const [schedule, setSchedule] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [loading, setLoading] = useState(false);
  const [activeDrag, setActiveDrag] = useState(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  const fetchSchedule = async () => {
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/generate-schedule`, {
        ...fakeData,
        manual_schedule: null,
      });
      setSchedule(res.data.schedule);
      setWarnings(res.data.statistics?.shortage_details || []);
      setHasUnsavedChanges(false);
    } catch (err) {
      alert("Server Connection Failed!");
    } finally {
      setLoading(false);
    }
  };

  const handleSaveSchedule = async () => {
    if (!schedule) return;
    setLoading(true);
    try {
      const res = await axios.post(`${API_URL}/generate-schedule`, {
        ...fakeData,
        manual_schedule: schedule,
      });
      setSchedule(res.data.schedule);
      setWarnings(res.data.statistics?.shortage_details || []);
      setHasUnsavedChanges(false);
      alert("Success: Schedule validated and saved!");
    } catch (err) {
      alert("Error saving schedule");
    } finally {
      setLoading(false);
    }
  };

  const onDragEnd = (event) => {
    const { active, over } = event;
    setActiveDrag(null);
    if (!over || !schedule) return;

    const emp = active.data.current.employee;
    const { dayIdx, shift } = over.data.current;

    const next = JSON.parse(JSON.stringify(schedule));

    ["M", "E", "N"].forEach((s) => {
      next[String(dayIdx)][s] = next[String(dayIdx)][s].filter((x) => x.id !== emp.id);
    });

    next[String(dayIdx)][shift].push({
      id: emp.id,
      name: emp.name,
      role: emp.role,
      is_senior: emp.is_senior,
    });

    setSchedule(next);
    setHasUnsavedChanges(true);
  };

  const handleRemove = (dayIdx, shift, empId) => {
    const next = { ...schedule };
    next[dayIdx][shift] = next[dayIdx][shift].filter((x) => x.id !== empId);
    setSchedule(next);
    setHasUnsavedChanges(true);
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-4 lg:p-8 font-sans antialiased text-slate-900">
      <div className="max-w-[1800px] mx-auto">
        <header className="flex justify-between items-center mb-10">
          <div>
            <h1 className="text-2xl font-black tracking-tight text-slate-800">AI STAFF SCHEDULER</h1>
            <p className="text-slate-400 text-sm font-medium">Drag and drop to manage shifts</p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={fetchSchedule}
              disabled={loading}
              className="bg-white border border-slate-200 px-6 py-2.5 rounded-xl font-bold text-sm shadow-sm hover:bg-slate-50 transition-all disabled:opacity-50"
            >
              {loading ? "Generating..." : "Generate AI Schedule"}
            </button>
            <button
              onClick={handleSaveSchedule}
              disabled={loading || !schedule || !hasUnsavedChanges}
              className="bg-blue-600 text-white px-6 py-2.5 rounded-xl font-bold text-sm shadow-lg shadow-blue-200 hover:bg-blue-700 transition-all disabled:opacity-50"
            >
              Validate & Save Changes
            </button>
          </div>
        </header>

        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={(e) => setActiveDrag(e.active.data.current?.employee)}
          onDragEnd={onDragEnd}
        >
          {/* ================= EMPLOYEE ROSTER ================= */}
          <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 mb-8">
            <h3 className="font-bold text-xs uppercase tracking-widest text-slate-400 mb-4">Available Personnel</h3>
            <SortableContext items={fakeData.employees.map(e => e.id)} strategy={horizontalListSortingStrategy}>
              <div className="flex flex-wrap gap-3">
                {fakeData.employees.map((emp) => (
                  <EmployeeItem key={emp.id} emp={emp} />
                ))}
              </div>
            </SortableContext>
          </div>

          <div className="flex flex-col lg:flex-row gap-8 items-start">
            {/* Main Schedule Area - SCROLLABLE HORIZONTALLY TO PREVENT SQUISHING */}
            <div className="flex-1 w-full overflow-hidden bg-white p-6 rounded-3xl shadow-sm border border-slate-100">
              <div className="overflow-x-auto pb-4">
                {schedule ? (
                  <div className="flex gap-4 min-w-[1200px]">
                    {Object.keys(schedule).map((d) => (
                      <div key={d} className="flex-1 min-w-[160px] space-y-4">
                        <div className="bg-blue-600 text-white text-center py-3 rounded-xl font-bold text-xs tracking-tighter uppercase shadow-md shadow-blue-100">
                          Day {parseInt(d) + 1}
                        </div>
                        {["M", "E", "N"].map((s) => (
                          <ShiftSlot
                            key={s}
                            dayIdx={d}
                            shift={s}
                            assigned={schedule[d][s] || []}
                            onRemove={handleRemove}
                          />
                        ))}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="h-[400px] flex flex-col items-center justify-center text-slate-300 gap-2 border-2 border-dashed border-slate-100 rounded-2xl">
                    <span className="text-4xl">🗓️</span>
                    <p className="font-medium">No schedule active. Click Generate to begin.</p>
                  </div>
                )}
              </div>
            </div>

            {/* Sidebar Warnings */}
            <div className="w-full lg:w-[350px] shrink-0">
              <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 sticky top-8">
                <h3 className={`font-bold uppercase text-[10px] tracking-[0.2em] mb-4 flex items-center gap-2 ${warnings.length > 0 ? 'text-rose-500' : 'text-emerald-500'}`}>
                   System Validation {warnings.length > 0 ? `(${warnings.length})` : ''}
                </h3>
                <div className="space-y-2">
                  {warnings.length > 0 ? (
                    warnings.map((w, i) => (
                      <div 
                        key={i} 
                        className="p-3 bg-rose-50 text-rose-700 text-[11px] font-bold rounded-lg border-l-4 border-rose-400"
                      >
                        {w}
                      </div>
                    ))
                  ) : (
                    <div className="p-10 text-center flex flex-col gap-3 items-center">
                      <div className="w-12 h-12 bg-emerald-50 text-emerald-500 flex items-center justify-center rounded-full text-xl animate-pulse">✓</div>
                      <p className="text-emerald-600 font-bold text-xs uppercase tracking-tight">Compliance Passed</p>
                      <p className="text-slate-400 text-[10px]">All labor laws and staffing requirements are satisfied.</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          <DragOverlay>
            {activeDrag ? <EmployeeItem emp={activeDrag} isOverlay /> : null}
          </DragOverlay>
        </DndContext>
      </div>
    </div>
  );
}