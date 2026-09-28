import { useRef, useState, type DragEvent } from "react";

export const ACCEPT = ".pdf,.png,.jpg,.jpeg,.xlsx";

export function UploadZone({ onFiles, active }: { onFiles: (files: File[]) => void; active: number }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length) onFiles(files);
  }

  return (
    <div
      className={`upload-zone${dragging ? " dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => input.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
    >
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          e.target.value = "";
        }}
      />
      <div className="upload-icon" aria-hidden>
        ⇪
      </div>
      <div>
        <strong>Drop purchase orders here</strong> or click to choose files
      </div>
      <div className="muted small">
        PDF, PNG, JPG or XLSX · several files at once · processed 3 at a time
        {active > 0 && <> · {active} in progress</>}
      </div>
    </div>
  );
}
