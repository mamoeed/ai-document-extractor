import { json } from "@codemirror/lang-json";
import { EditorView } from "@codemirror/view";
import CodeMirror from "@uiw/react-codemirror";

const extensions = [json(), EditorView.lineWrapping];

export function JsonEditor({
  value,
  onChange,
  readOnly,
}: {
  value: string;
  onChange: (value: string) => void;
  readOnly: boolean;
}) {
  return (
    <div className={`json-editor${readOnly ? " readonly" : ""}`}>
      <CodeMirror
        value={value}
        onChange={onChange}
        readOnly={readOnly}
        editable={!readOnly}
        extensions={extensions}
        basicSetup={{ foldGutter: true, highlightActiveLine: !readOnly }}
        maxHeight="520px"
      />
    </div>
  );
}
