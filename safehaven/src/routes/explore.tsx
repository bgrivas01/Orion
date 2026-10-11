import {createFileRoute} from '@tanstack/react-router';
import {ExploreScreen} from '@/components/safety-screens';
import {pageHead} from '@/lib/page-head';
export const Route=createFileRoute('/explore')({head:()=>pageHead('Explore a location','Search Orion addresses and choose a route origin.'),component:ExploreScreen});
