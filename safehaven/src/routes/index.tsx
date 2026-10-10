import {createFileRoute} from '@tanstack/react-router';
import {HomeScreen} from '@/components/safety-screens';
import {pageHead} from '@/lib/page-head';
export const Route=createFileRoute('/')({head:()=>pageHead('Your safety at a glance','View your safety score, current flood warning and 72-hour demo forecast.'),component:HomeScreen});
