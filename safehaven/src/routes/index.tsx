import {createFileRoute} from '@tanstack/react-router';
import {HomeScreen} from '@/components/safety-screens';
import {pageHead} from '@/lib/page-head';
export const Route=createFileRoute('/')({head:()=>pageHead('Your flood-awareness workspace','View Orion warnings and plan flood-aware routes.'),component:HomeScreen});
