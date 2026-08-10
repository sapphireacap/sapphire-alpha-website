import { useEffect, useRef, useState } from "react";

// Compares `value` against its own previous render and returns a
// short-lived CSS class ("term-flash-up" / "term-flash-down" / "") for
// ~400ms after it changes -- used to flash a cell's background on the
// existing 1-minute data refresh, without ever permanently recoloring it.
export default function useFlash(value) {
  const prevRef = useRef(value);
  const [flashClass, setFlashClass] = useState("");

  useEffect(() => {
    const prev = prevRef.current;
    if (prev != null && value != null && value !== prev) {
      setFlashClass(value > prev ? "term-flash-up" : "term-flash-down");
      const t = setTimeout(() => setFlashClass(""), 400);
      prevRef.current = value;
      return () => clearTimeout(t);
    }
    prevRef.current = value;
    return undefined;
  }, [value]);

  return flashClass;
}
