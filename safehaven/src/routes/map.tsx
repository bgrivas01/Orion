import {createFileRoute} from '@tanstack/react-router';
import {MapScreen} from '@/components/safety-screens';
import {pageHead} from '@/lib/page-head';
export const Route=createFileRoute('/map')({head:()=>pageHead('Flood-aware route planner','Plan real road routes using Orion warning exposure and hazard assessments.'),component:MapScreen});
