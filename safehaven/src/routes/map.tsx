import {createFileRoute} from '@tanstack/react-router';
import {MapScreen} from '@/components/safety-screens';
import {pageHead} from '@/lib/page-head';
export const Route=createFileRoute('/map')({head:()=>pageHead('Your way to safety','Explore an illustrative evacuation route and saved emergency directions.'),component:MapScreen});
