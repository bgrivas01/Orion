import {createFileRoute} from '@tanstack/react-router';
import {ThreatScreen} from '@/components/safety-screens';
import {pageHead} from '@/lib/page-head';
export const Route=createFileRoute('/threat')({head:()=>pageHead('Warnings and observations','View Orion warning areas, river gauges and dated flood observations.'),component:ThreatScreen});
