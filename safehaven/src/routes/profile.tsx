import {createFileRoute} from '@tanstack/react-router';
import {ProfileScreen} from '@/components/safety-screens';
import {pageHead} from '@/lib/page-head';
export const Route=createFileRoute('/profile')({head:()=>pageHead('Your profile and preferences','Manage saved locations, emergency contacts and safety preferences.'),component:ProfileScreen});
