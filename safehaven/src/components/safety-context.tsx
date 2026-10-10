import { createContext, useContext, useState, type ReactNode } from 'react';
const SafetyContext = createContext<ReturnType<typeof useSafetyState> | null>(null);
function useSafetyState() {
 const [offline, setOffline] = useState(false);
 const [light, setLight] = useState(false);
 const [panic, setPanic] = useState(false);
 const [danger, setDanger] = useState(false);
 const [checked, setChecked] = useState<string[]>([]);
 const [downloaded, setDownloaded] = useState(true);
 return {offline,setOffline,light,setLight,panic,setPanic,danger,setDanger,checked,setChecked,downloaded,setDownloaded};
}
export function SafetyProvider({children}:{children:ReactNode}) { const state=useSafetyState(); return <SafetyContext.Provider value={state}><div className={state.light?'light':''}>{children}</div></SafetyContext.Provider> }
export function useSafety() { const state=useContext(SafetyContext); if(!state) throw new Error('SafetyProvider missing'); return state; }
