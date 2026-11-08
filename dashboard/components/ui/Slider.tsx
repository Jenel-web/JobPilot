"use client";

/** A labelled range slider with the current value on the right (Settings thresholds). */
export function Slider({
  label,
  value,
  onChange,
  min = 0,
  max = 100,
  unit = "",
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  unit?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between text-sm">
        <label htmlFor={`slider-${label}`}>{label}</label>
        <span className="tabular font-semibold">
          {value}
          {unit}
        </span>
      </div>
      <input
        id={`slider-${label}`}
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 w-full cursor-pointer accent-jp-brand"
      />
    </div>
  );
}
