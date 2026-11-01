const paths = {
  folder: "M3.5 7.5v9A1.5 1.5 0 0 0 5 18h14a1.5 1.5 0 0 0 1.5-1.5v-8A1.5 1.5 0 0 0 19 7h-7.2L9.5 4.5h-4a2 2 0 0 0-2 2z",
  file: "M6 2h8l4 4v16H6z M14 2v5h5 M9 12h6 M9 16h6",
  "file-csv": "M6 2h8l4 4v16H6z M14 2v5h5 M9 11h1.5 M9 15h1.5 M13 11h2 M13 15h2 M16.5 11H18 M16.5 15H18 M9 19h1.5 M13 19h2 M16.5 19H18",
  "file-json": "M6 2h8l4 4v16H6z M14 2v5h5 M11 10c-1.5 0-1.5 2-1.5 2s0 2-1.5 2c1.5 0 1.5 2 1.5 2s0 2 1.5 2 M15 10c1.5 0 1.5 2 1.5 2s0 2 1.5 2c-1.5 0-1.5 2-1.5 2s0 2-1.5 2",
  system: "M5 4.5h14A1.5 1.5 0 0 1 20.5 6v9a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 15V6A1.5 1.5 0 0 1 5 4.5z M9 20h6 M12 16.5V20",
  database: "M20 5c0 2-3.6 3-8 3S4 7 4 5s3.6-3 8-3 8 1 8 3z M4 5v14c0 2 3.6 3 8 3s8-1 8-3V5 M4 12c0 2 3.6 3 8 3s8-1 8-3",
  logs: "M5 3h14v18H5z M8 7h8 M8 11h8 M8 15h5",
  components: "M9 3h6l1 4 4 1v8l-4 1-1 4H9l-1-4-4-1V8l4-1z M9 12a3 3 0 1 0 6 0 3 3 0 0 0-6 0",
  shield: "M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6z M8 12l3 3 5-6",
  statistics: "M4 3v18h17 M8 17v-6 M13 17V7 M18 17V4",
  audit: "M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6z M12 7v6 M12 16v1",
  network: "M7 5.5a2.5 2.5 0 1 0-2.5 2.5A2.5 2.5 0 0 0 7 5.5z M19.5 3a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z M19.5 16a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z M6.8 9.9l10.1-4 M6.8 10.1l10.1 4",
  "check-circle": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M8 12l2.5 2.5L16 9",
  warning: "M10.3 3.5 2.7 17a2 2 0 0 0 1.7 3h15.2a2 2 0 0 0 1.7-3L13.7 3.5a2 2 0 0 0-3.4 0z M12 9v4 M12 17h.01",
  "minus-circle": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M8 12h8",
  "chevron-down": "m6 9 6 6 6-6",
  "external-link": "M14 3h7v7 M21 3l-9 9 M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6",
  settings: "M9 3h6l1 4 4 1v8l-4 1-1 4H9l-1-4-4-1V8l4-1z M9 12a3 3 0 1 0 6 0 3 3 0 0 0-6 0",
  menu: "M4 6h16 M4 12h16 M4 18h16",
  back: "m14 5-7 7 7 7 M7 12h14",
  refresh: "M20 7v5h-5 M4 17v-5h5 M5 8a8 8 0 0 1 13-3l2 3 M4 16l2 3a8 8 0 0 0 13-3",
  copy: "M8 8h13v13H8z M16 8V3H3v13h5",
  edit: "m16 3 5 5 M4 16l12.5-12.5a2.8 2.8 0 0 1 4 4L8 20l-5 1z",
  trash: "M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7",
  download: "M12 3v12 m-5-5 5 5 5-5 M5 16v5h14v-5",
  upload: "M12 15V3 m-5 5 5-5 5 5 M5 16v5h14v-5",
  plus: "M12 5v14 M5 12h14",
  play: "m8 5 12 7-12 7z",
  save: "M5 3h12l4 4v14H3V3z M7 3v6h10V3 M7 21v-8h10v8",
  expand: "M9 3H3v6 M15 3h6v6 M21 15v6h-6 M3 15v6h6",
  close: "m5 5 14 14 M19 5 5 19",
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  return <svg className={`ui-icon ${className}`.trim()} viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[name]} /></svg>;
}
