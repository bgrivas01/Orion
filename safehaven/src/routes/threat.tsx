import {createFileRoute} from '@tanstack/react-router';
import {ThreatScreen} from '@/components/safety-screens';
import {pageHead} from '@/lib/page-head';
export const Route=createFileRoute('/threat')({head:()=>pageHead('Flood warning details','Explore flood intensity, rainfall, wind and predicted hazard changes.'),component:ThreatScreen});
