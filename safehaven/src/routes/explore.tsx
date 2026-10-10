import {createFileRoute} from '@tanstack/react-router';
import {ExploreScreen} from '@/components/safety-screens';
import {pageHead} from '@/lib/page-head';
export const Route=createFileRoute('/explore')({head:()=>pageHead('Safety score explorer','Explore illustrative location safety scores and hazard risk factors.'),component:ExploreScreen});
