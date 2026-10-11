import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Outlet, Link, createRootRouteWithContext, HeadContent, Scripts } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { SafetyProvider } from '@/components/safety-context';
import { SafetyShell } from '@/components/safety-shell';
import appCss from '../styles.css?url';
export const Route = createRootRouteWithContext<{queryClient:QueryClient}>()({head:()=>({meta:[{charSet:'utf-8'},{name:'viewport',content:'width=device-width, initial-scale=1'}],links:[{rel:'stylesheet',href:appCss},{rel:'stylesheet',href:'https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap'}]}),shellComponent:RootShell,component:RootComponent,notFoundComponent:()=> <div className="page"><h1>Page not found</h1><Link to="/">Go home</Link></div>});
function RootShell({children}:{children:ReactNode}){return <html lang="en"><head><HeadContent/></head><body>{children}<Scripts/></body></html>}
function RootComponent(){const {queryClient}=Route.useRouteContext();return <QueryClientProvider client={queryClient}><SafetyProvider><SafetyShell><Outlet/></SafetyShell></SafetyProvider></QueryClientProvider>}
