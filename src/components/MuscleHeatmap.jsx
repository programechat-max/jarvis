/**
 * Profesyonel kas ısı haritası — Heavy Duty / anatomik referans stiline yakın.
 * Ön + arka görünüm, gri kas dokusu üzerine termal renk katmanı.
 */

const MUSCLE_GROUPS = ['Göğüs', 'Sırt', 'Omuz', 'Kol', 'Karın', 'Bacak'];

function getHeatColor(sets) {
  if (!sets || sets === 0) return null;
  if (sets <= 3) return { fill: '#14b8a6', glow: 'rgba(20,184,166,0.45)' };
  if (sets <= 6) return { fill: '#f59e0b', glow: 'rgba(245,158,11,0.5)' };
  if (sets <= 10) return { fill: '#f97316', glow: 'rgba(249,115,22,0.55)' };
  if (sets <= 15) return { fill: '#ef4444', glow: 'rgba(239,68,68,0.6)' };
  return { fill: '#b91c1c', glow: 'rgba(185,28,28,0.65)' };
}

function muscleStyle(group, data) {
  const sets = data[group]?.sets || 0;
  const heat = getHeatColor(sets);
  if (!heat) {
    return {
      fill: '#3f3f46',
      stroke: '#52525b',
      strokeWidth: 0.6,
      filter: undefined,
    };
  }
  return {
    fill: heat.fill,
    stroke: '#18181b',
    strokeWidth: 0.8,
    filter: `drop-shadow(0 0 6px ${heat.glow})`,
  };
}

function MusclePath({ d, group, data, extra = {} }) {
  const s = muscleStyle(group, data);
  return (
    <path
      d={d}
      fill={s.fill}
      stroke={s.stroke}
      strokeWidth={s.strokeWidth}
      strokeLinejoin="round"
      style={extra.opacity ? { opacity: extra.opacity, filter: s.filter } : { filter: s.filter }}
    />
  );
}

function DetailLines({ paths }) {
  return paths.map((d, i) => (
    <path key={i} d={d} fill="none" stroke="#18181b" strokeWidth="0.4" opacity="0.55" />
  ));
}

function BodyView({ side, data }) {
  const isFront = side === 'front';
  const label = isFront ? 'ÖN' : 'ARKA';

  return (
    <g>
      <text x="100" y="14" textAnchor="middle" fill="#71717a" fontSize="9" fontFamily="monospace" letterSpacing="2">
        {label}
      </text>

      {/* Kafa & boyun — nötr */}
      <ellipse cx="100" cy="38" rx="18" ry="20" fill="#27272a" stroke="#3f3f46" strokeWidth="0.6" />
      <rect x="91" y="55" width="18" height="12" rx="4" fill="#27272a" stroke="#3f3f46" strokeWidth="0.5" />

      {isFront ? (
        <>
          {/* Trapez (üst) */}
          <MusclePath group="Sırt" data={data} d="M72,66 L100,58 L128,66 L118,78 L100,72 L82,78 Z" />
          {/* Omuzlar */}
          <MusclePath group="Omuz" data={data} d="M58,78 C44,82 38,96 42,112 C44,122 52,128 60,124 C66,120 64,100 62,88 C60,82 58,78 58,78 Z" />
          <MusclePath group="Omuz" data={data} d="M142,78 C156,82 162,96 158,112 C156,122 148,128 140,124 C134,120 136,100 138,88 C140,82 142,78 142,78 Z" />
          {/* Göğüs */}
          <MusclePath group="Göğüs" data={data} d="M100,72 C82,70 68,78 64,96 C62,110 74,124 100,120 L100,72 Z" />
          <MusclePath group="Göğüs" data={data} d="M100,72 C118,70 132,78 136,96 C138,110 126,124 100,120 L100,72 Z" />
          <DetailLines paths={[
            'M100,76 L100,118',
            'M78,88 C88,96 100,98 100,98',
            'M122,88 C112,96 100,98 100,98',
          ]} />
          {/* Biceps / kol */}
          <MusclePath group="Kol" data={data} d="M46,118 C38,122 34,138 38,158 C40,172 48,178 54,172 C58,166 56,148 52,130 C50,122 46,118 46,118 Z" />
          <MusclePath group="Kol" data={data} d="M154,118 C162,122 166,138 162,158 C160,172 152,178 146,172 C142,166 144,148 148,130 C150,122 154,118 154,118 Z" />
          <MusclePath group="Kol" data={data} d="M40,174 C36,178 34,196 38,214 C40,224 46,228 50,224 C54,218 52,200 48,182 Z" />
          <MusclePath group="Kol" data={data} d="M160,174 C164,178 166,196 162,214 C160,224 154,228 150,224 C146,218 148,200 152,182 Z" />
          {/* Karın */}
          <MusclePath group="Karın" data={data} d="M84,122 L116,122 L114,138 L86,138 Z" />
          <MusclePath group="Karın" data={data} d="M84,140 L116,140 L114,156 L86,156 Z" />
          <MusclePath group="Karın" data={data} d="M84,158 L116,158 L112,172 L88,172 Z" />
          <DetailLines paths={['M100,122 L100,172', 'M84,130 L116,130', 'M84,148 L116,148', 'M86,164 L114,164']} />
          {/* Quad */}
          <MusclePath group="Bacak" data={data} d="M78,174 C70,190 68,228 72,268 C74,282 84,284 90,278 C94,272 92,236 88,204 C86,188 82,178 78,174 Z" />
          <MusclePath group="Bacak" data={data} d="M122,174 C130,190 132,228 128,268 C126,282 116,284 110,278 C106,272 108,236 112,204 C114,188 118,178 122,174 Z" />
          <DetailLines paths={['M86,200 L86,260', 'M114,200 L114,260', 'M100,190 L100,270']} />
          {/* Baldır — nötr */}
          <path d="M74,282 C72,296 74,318 78,332 C80,338 86,338 88,332 C90,318 88,296 86,282 Z" fill="#27272a" stroke="#3f3f46" strokeWidth="0.5" />
          <path d="M126,282 C128,296 126,318 122,332 C120,338 114,338 112,332 C110,318 112,296 114,282 Z" fill="#27272a" stroke="#3f3f46" strokeWidth="0.5" />
        </>
      ) : (
        <>
          {/* Trapez + üst sırt */}
          <MusclePath group="Sırt" data={data} d="M68,64 L100,54 L132,64 L126,92 L100,84 L74,92 Z" />
          <MusclePath group="Sırt" data={data} d="M74,92 C62,102 56,128 66,152 C74,166 90,170 100,162 L100,84 Z" />
          <MusclePath group="Sırt" data={data} d="M126,92 C138,102 144,128 134,152 C126,166 110,170 100,162 L100,84 Z" />
          <DetailLines paths={[
            'M100,60 L100,162',
            'M82,100 C92,108 100,110 100,110',
            'M118,100 C108,108 100,110 100,110',
            'M78,130 L122,130',
          ]} />
          {/* Arka omuz */}
          <MusclePath group="Omuz" data={data} d="M58,78 C44,82 38,96 42,112 C44,122 52,128 60,124 C66,120 64,100 62,88 Z" />
          <MusclePath group="Omuz" data={data} d="M142,78 C156,82 162,96 158,112 C156,122 148,128 140,124 C134,120 136,100 138,88 Z" />
          {/* Triceps */}
          <MusclePath group="Kol" data={data} d="M46,118 C38,122 34,138 38,158 C40,172 48,178 54,172 C58,166 56,148 52,130 Z" />
          <MusclePath group="Kol" data={data} d="M154,118 C162,122 166,138 162,158 C160,172 152,178 146,172 C142,166 144,148 148,130 Z" />
          <MusclePath group="Kol" data={data} d="M40,174 C36,178 34,196 38,214 C40,224 46,228 50,224 C54,218 52,200 48,182 Z" />
          <MusclePath group="Kol" data={data} d="M160,174 C164,178 166,196 162,214 C160,224 154,228 150,224 C146,218 148,200 152,182 Z" />
          {/* Alt sırt / bel */}
          <MusclePath group="Sırt" data={data} d="M86,162 L114,162 L110,178 L90,178 Z" />
          {/* Glute + hamstring */}
          <MusclePath group="Bacak" data={data} d="M74,178 C66,182 64,200 68,216 C72,228 88,230 92,218 C94,206 90,188 84,178 Z" />
          <MusclePath group="Bacak" data={data} d="M126,178 C134,182 136,200 132,216 C128,228 112,230 108,218 C106,206 110,188 116,178 Z" />
          <MusclePath group="Bacak" data={data} d="M76,218 C72,238 72,262 76,280 C78,288 86,288 88,280 C90,262 90,238 84,222 Z" />
          <MusclePath group="Bacak" data={data} d="M124,218 C128,238 128,262 124,280 C122,288 114,288 112,280 C110,262 110,238 116,222 Z" />
          <DetailLines paths={['M88,200 L88,276', 'M112,200 L112,276', 'M100,178 L100,282']} />
          {/* Baldır — nötr */}
          <path d="M74,288 C72,302 74,318 78,332 C80,338 86,338 88,332 C90,318 88,302 86,288 Z" fill="#27272a" stroke="#3f3f46" strokeWidth="0.5" />
          <path d="M126,288 C128,302 126,318 122,332 C120,338 114,338 112,332 C110,318 112,302 114,288 Z" fill="#27272a" stroke="#3f3f46" strokeWidth="0.5" />
        </>
      )}
    </g>
  );
}

export default function MuscleHeatmap({ data = {} }) {
  const sets = (group) => data[group]?.sets || 0;
  const totalSets = MUSCLE_GROUPS.reduce((acc, g) => acc + sets(g), 0);

  return (
    <div className="flex flex-col lg:flex-row items-center gap-8">
      <div className="relative rounded-2xl overflow-hidden border border-neutral-800 bg-black p-4 w-full max-w-lg">
        <div className="absolute inset-0 bg-gradient-to-b from-neutral-900/20 to-transparent pointer-events-none" />
        <svg viewBox="0 0 420 360" className="w-full h-auto">
          <defs>
            <linearGradient id="bodyBg" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#0a0a0a" />
              <stop offset="100%" stopColor="#171717" />
            </linearGradient>
          </defs>
          <rect width="420" height="360" fill="url(#bodyBg)" rx="8" />
          <g transform="translate(10, 16)">
            <BodyView side="front" data={data} />
          </g>
          <g transform="translate(210, 16)">
            <BodyView side="back" data={data} />
          </g>
        </svg>
        <p className="text-center text-[10px] font-mono text-neutral-600 mt-2">
          {totalSets > 0 ? `${totalSets} toplam set` : 'Bugün henüz set kaydı yok'}
        </p>
      </div>

      <div className="w-full lg:w-52 space-y-4">
        <p className="text-[10px] font-mono uppercase text-neutral-500 tracking-wider">Kas Grubu</p>
        <div className="space-y-2">
          {MUSCLE_GROUPS.map((group) => {
            const s = sets(group);
            const heat = getHeatColor(s);
            return (
              <div key={group} className="flex items-center gap-3">
                <span
                  className="w-4 h-4 rounded-sm shrink-0 border border-neutral-700"
                  style={{ backgroundColor: heat?.fill || '#3f3f46' }}
                />
                <span className="text-sm text-neutral-300 flex-1">{group}</span>
                <span className="text-xs font-mono text-neutral-500">{s} set</span>
              </div>
            );
          })}
        </div>

        <div className="pt-3 border-t border-neutral-800">
          <p className="text-[10px] font-mono uppercase text-neutral-600 mb-2">Yoğunluk</p>
          <div className="flex h-2 rounded-full overflow-hidden">
            {['#3f3f46', '#14b8a6', '#f59e0b', '#f97316', '#ef4444', '#b91c1c'].map((c) => (
              <div key={c} className="flex-1" style={{ backgroundColor: c }} />
            ))}
          </div>
          <div className="flex justify-between text-[9px] font-mono text-neutral-600 mt-1">
            <span>0</span>
            <span>3</span>
            <span>6</span>
            <span>10</span>
            <span>15+</span>
          </div>
        </div>
      </div>
    </div>
  );
}
